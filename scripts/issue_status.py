"""Pure lifecycle/Prow reports; notification identity never depends on Markdown.

Runtime validates stage/delivery authority and supplies the effective stage and
parsed delivery evidence. ``notification_action`` identifies the semantic action;
the writer combines it with the authorized ``request_id`` for notification dedup.
Formatting, catalog display names and bot projection events are not action identity.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re


STAGES = {
    "needs-triage": "Waiting on Maintainer",
    "triage/needs-information": "Waiting for information or a decision",
    "triage/accepted": "Accepted for implementation",
    "awaiting-release": "Fix awaiting delivery",
    "needs-verification": "Published fix awaiting reporter verification",
}
NO_ACTION = "No action needed unless information is requested."


def _labels(record):
    return {
        label if isinstance(label, str) else label["name"]
        for label in record.get("labels", [])
    }


def _action(kind, details):
    payload = json.dumps(details, sort_keys=True, separators=(",", ":"))
    return kind + ":" + hashlib.sha256(payload.encode()).hexdigest()


def _request(record, facts, marker, request_event):
    if not request_event or request_event.get("actor", {}).get("type") != "User":
        return None
    reporter = record.get("user", {}).get("login", "")
    grant_time = datetime.fromisoformat(request_event["created_at"].replace("Z", "+00:00"))

    def paired(comment):
        created = datetime.fromisoformat(comment["created_at"].replace("Z", "+00:00"))
        return created >= grant_time or (
            comment.get("user", {}).get("login") == request_event.get("actor", {}).get("login")
            and 0 <= (grant_time - created).total_seconds() <= 300
        )

    requests = [
        comment
        for comment in facts.get("comments", [])
        if comment.get("user", {}).get("type") == "User"
        and facts.get("permissions", {}).get(comment["user"].get("login"))
        in {"write", "maintain", "admin"}
        and paired(comment)
        and reporter
        and re.search(r"(?<![\w@])@" + re.escape(reporter) + r"(?![\w-])", comment.get("body") or "", re.I)
        and not any(reply.get("user", {}).get("login") == reporter
                    and reply.get("created_at", "") > comment.get("created_at", "")
                    for reply in facts.get("comments", []))
        and marker not in (comment.get("body") or "")
        and "factory issue pipeline" not in (comment.get("body") or "")
        and (
            "?" in (comment.get("body") or "")
            or re.search(r"\bplease\b", comment.get("body") or "", re.I)
        )
    ]
    return max(
        requests,
        key=lambda comment: (comment.get("created_at", ""), comment.get("id") or 0),
        default=None,
    )


def _delivery_fields(delivery_type):
    target = (
        "`Image: <published image>@sha256:<64-hex-digest>`"
        if delivery_type == "image"
        else "`Package: <published application/package>` and `Version: <published version>`"
    )
    return [
        f"Record {target} under **Delivery evidence** in the issue body.",
        "Add `Fix revision: <40-hex-commit>`, `Release/build: https://<published-release-or-build>`, and `Verify: <specific update and reproduction steps>`.",
    ]


def _render(marker, status, actor, transition, roles, reporter, reporter_steps=()):
    lines = [marker, f"**Status:** {status}"]
    owner = next((role for role in roles if actor.startswith(role)), next(iter(roles), None))
    for role, steps in roles.items():
        next_step = (f"Next: {transition}",) if transition and role == owner and not actor.startswith("Reporter") else ()
        if steps or next_step:
            heading = actor if actor.startswith(role + " (") else role
            lines.extend(["", f"## {heading}", ""])
            lines.extend(f"- {step}" for step in (*steps, *next_step))
    lines.extend(["", "## Reporter", "", f"**Reporter action:** {reporter}"])
    if transition and actor.startswith("Reporter"):
        reporter_steps = (*reporter_steps, f"Next: {transition}")
    if reporter_steps:
        lines.append("")
        lines.extend(f"- {step}" for step in reporter_steps)
    return "\n".join(lines)


def _pr_report(record, facts, catalog):
    pr = facts.get("pull_request", {})
    roles = {}
    if pr.get("draft"):
        status, actor = "Draft implementation", "PR contributor"
        roles["PR contributor"] = [
            "Finish the agreed changes and tests, then select GitHub's **Ready for review** control.",
        ]
        transition = "Draft → ready for native PR review."
    elif pr.get("native_mergeable") == "CONFLICTING":
        status, actor = "PR has merge conflicts", "PR contributor"
        roles["PR contributor"] = [
            "Resolve conflicts against the target branch and run the relevant tests.",
            "Address outstanding review requests, then re-request review using GitHub's **Reviewers** picker.",
        ]
        transition = "Conflicts resolved → native review and required checks."
    elif pr.get("review_decision") == "CHANGES_REQUESTED":
        status, actor = "Reviewer requested changes", "PR contributor"
        roles["PR contributor"] = [
            "Address the outstanding review findings and run the relevant tests.",
            "Re-request review of the new head using GitHub's **Reviewers** picker.",
        ]
        transition = "Updated PR head → renewed native review."
    elif pr.get("review_decision") == "APPROVED":
        status = "Native review approved; required checks and merge controls still apply"
        actor = "PR contributor for failing checks; maintainer / native merge automation after checks pass"
        roles["PR contributor"] = ["Resolve any failing required checks; approval alone is not a merge."]
        roles["Maintainer / native merge automation"] = [
            "Use the repository's native merge controls and merge queue after required checks pass; do not bypass them.",
        ]
        transition = "Required checks and native merge controls satisfied → merge, not proof of delivery."
    else:
        status, actor = "Awaiting native PR review", "Requested reviewers"
        roles["Requested reviewers"] = ["Review the current PR head using GitHub's **Review changes** control."]
        roles["PR contributor"] = ["Address requested changes and re-request review using GitHub's **Reviewers** picker."]
        transition = "Native review → changes requested or approval; required checks and merge controls still apply."
    roles.setdefault("PR contributor", []).append(
        "Link unresolved product reports with `Refs #NNN`, not `Closes #NNN`; preserve assignments, reviews, and merge-queue decisions."
    )
    return {
        "comment": _render(catalog["comment_marker"], status, actor, transition, roles,
                           "No action needed here; reply on the linked issue if it requests information or verification."),
        "notify_reporter": False,
        "notification_action": None,
    }


def status_report(record, facts, catalog, context):
    """Return comment, notify_reporter and semantic notification_action.

    Context: stage, approved, tracking, human_only, automatic_gate, missing,
    requester, delivery_evidence, close; optional kind_ambiguous. Record/facts
    retain GitHub assignees, labels, linked_prs, comments and permissions.
    Requests addressed to maintainers never notify reporters, even with missing
    form fields. The caller owns mentions, request-event anchors and API writes.
    """
    marker, display = catalog["comment_marker"], catalog["display_name"]
    delivery_type = catalog["delivery"]["type"]
    if delivery_type not in {"image", "release"}:
        raise ValueError("Unsupported delivery type")
    if "pull_request" in record:
        return _pr_report(record, facts, catalog)
    stage = context["stage"]
    if stage not in STAGES:
        raise ValueError("Unsupported issue stage")
    labels = _labels(record)
    approved = context.get("approved", False)
    tracking = context.get("tracking", False)
    human_only = context.get("human_only", False)
    missing = context.get("missing", [])
    evidence = context.get("delivery_evidence")
    required = {"revision", "url", "verify"} | ({"image"} if delivery_type == "image" else {"package", "version"})
    complete_evidence = bool(evidence and all(evidence.get(key) for key in required))
    roles = {"Maintainer": []}
    maintainer = roles["Maintainer"]
    status, actor = STAGES[stage], "Maintainer"
    reporter = NO_ACTION
    reporter_steps = []
    notification_action = None
    transition = "Maintainer review → `triage/accepted`, `triage/needs-information`, or closure with a reason."
    blockers = labels & {"blocked", "hold"}
    independent_gate = "needs-human" in labels and not context.get("automatic_gate", False)
    native_gates = set(context.get("active_gate_labels", labels & set(catalog.get("gate_labels", [])))) - {"blocked", "hold", "needs-human", "human-only"}
    effective_kind = context.get("kind", {label for label in labels if label.startswith("kind/")})
    kind_missing = not effective_kind
    stale = "triage/accepted" in labels and not approved
    gated = bool(blockers or independent_gate or native_gates or kind_missing or context.get("kind_ambiguous") or not approved)

    if kind_missing or context.get("kind_ambiguous"):
        maintainer.append(
            "Use GitHub's **Labels** picker to select exactly one catalog `kind/*` label before scheduling; remove conflicting kind labels."
        )
    if stale:
        maintainer.append(
            "The current scope lacks valid human acceptance or changed after approval. Review the body scope and completion criteria first, then use GitHub's **Labels** picker to select `triage/accepted` again for fresh acceptance."
        )
    if blockers:
        status += " — " + " / ".join(sorted(blockers))
        actor = "Maintainer / blocker or hold owner"
        roles["Blocker / hold owner"] = [
            "Resolve the recorded dependency or hold reason; the owner then removes "
            + " and ".join(f"`{label}`" for label in sorted(blockers))
            + " using GitHub's **Labels** picker before new implementation dispatch.",
            "Preserve existing assignments, branches, PRs, reviews, and merge-queue decisions.",
        ]
    if native_gates and not context.get("close"):
        gate_names = " and ".join(f"`{label}`" for label in sorted(native_gates))
        roles["Human gate owner"] = [
            f"Resolve the recorded question or human decision behind {gate_names} and update the agreed scope and completion criteria in the issue body.",
            f"The gate's owner then explicitly removes {gate_names} using GitHub's **Labels** picker only when its reason is resolved; do not remove a gate merely to dispatch work.",
            "A maintainer must record any fresh implementation acceptance with `triage/accepted`; acceptance does not clear native human gates or assign a contributor.",
        ]
    if human_only:
        maintainer.append(
            "Preserve the reporter's `human-only` preference: use human interaction and human contributors, not machine analysis or agent implementation."
        )

    if tracking:
        status = "Standing tracker — not an implementation assignment" + (
            " — " + " / ".join(sorted(blockers)) if blockers else ""
        )
        maintainer.extend([
            "Maintain this tracker and link actionable child issues in its body or comments.",
            "Triage and assign each child issue separately; do not dispatch this tracker as an implementation task.",
        ])
        transition = "Tracker remains open; actionable child issues follow their own lifecycle."
    elif context.get("close"):
        if stage != "needs-verification" or not complete_evidence:
            raise ValueError("Confirmed closure requires a verification stage and delivery evidence")
        status, actor = "Reporter confirmed the published fix", "Lifecycle automation"
        roles["Lifecycle automation"] = ["Close this report as completed after the recorded reporter confirmation."]
        maintainer.append("Retain the delivery evidence and the reporter's tested version in this issue.")
        transition = "Reporter confirmation → closed as completed."
        reporter = "No action needed; reopen or file a linked report if the problem returns."
    elif stage == "needs-triage":
        maintainer.extend([
            "Review, use GitHub's **Labels** picker to add `triage/accepted` if you approve implementation.",
            "Do not remove `needs-triage` or `needs-human` to signal approval: the bot restores them until acceptance is recorded.",
            "Acceptance does not assign a contributor.",
            f"If a specific question prevents acceptance, ask it and select `triage/needs-information`; if declining or marking a duplicate, close with the reason. `/hive approve` is not a {display} lifecycle acceptance action.",
        ])
    elif stage == "triage/needs-information":
        if context.get("requester") == "maintainer" or record.get("user", {}).get("type") != "User":
            status = "Waiting on Maintainer decision" + (" — blocked / held" if blockers else "")
            maintainer.extend([
                "Resolve the recorded decision and update the agreed scope and completion criteria in the issue body first.",
                "Remove `needs-decision` in GitHub's **Labels** picker only after its reason is resolved, then select `triage/accepted` to accept the updated scope."
                if "needs-decision" in labels else
                "After the missing fact or decision is resolved, use GitHub's **Labels** picker to select `triage/accepted` for the agreed scope.",
                "Removing a waiting label or posting `/hive approve` does not record lifecycle acceptance.",
            ])
            if missing:
                maintainer.append("Clarify who can supply the missing fields: " + ", ".join(f"**{field}**" for field in missing) + ".")
            transition = "Maintainer resolves decision and records fresh acceptance → `triage/accepted`."
        elif missing:
            actor = "Reporter"
            reporter = "Provide the requested information in an ordinary reply or the corresponding issue form fields."
            reporter_steps = [f"Supply **{field}**." for field in missing]
            if delivery_type == "image" and "image details" in missing:
                reporter_steps.append("Run `bootc status` and paste the complete output, or explain that the machine cannot boot, the command fails, or it is not applicable.")
            elif delivery_type == "release" and any("version" in field.lower() or "application" in field.lower() or "package" in field.lower() for field in missing):
                reporter_steps.append(f"Include the installed {display} package/version and installation source; do not substitute an unrelated image digest.")
            maintainer.append("Reassess the reporter's ordinary reply or body edit; acceptance still requires a fresh maintainer decision in GitHub's **Labels** picker.")
            notification_action = _action("information-fields", sorted(set(missing)))
            transition = "Reporter reply or field edit → `needs-triage` for maintainer reassessment, not automatic acceptance."
        else:
            request = _request(record, facts, marker, context.get("request_event"))
            if request:
                actor = "Reporter"
                reference = (
                    f"[the maintainer's request]({request['html_url']})"
                    if request.get("html_url") else f"the maintainer's comment #{request['id']}"
                )
                reporter = f"Answer {reference} in an ordinary reply; no label access or slash command is needed."
                maintainer.append("Reassess the reporter's reply before recording any fresh implementation acceptance.")
                notification_action = _action("information-comment", request.get("id") or request.get("html_url"))
                transition = "Reporter reply → `needs-triage` for maintainer reassessment."
            else:
                maintainer.append("Select `triage/needs-information`, then post the exact request in a new comment and explicitly @mention the reporter only if they must answer; otherwise name the responsible maintainer.")
                reporter = "No action needed until a maintainer states the exact request and names who should answer."
                transition = "Explicit maintainer request → the named person's reply, then maintainer reassessment."
    elif stage == "triage/accepted":
        if not approved:
            status = "Implementation acceptance is not valid for the current scope"
        if independent_gate and not human_only:
            maintainer.append("A human or app added an independent `needs-human` gate. Resolve its recorded reason, then its owner explicitly removes that label using GitHub's **Labels** picker only when implementation is allowed; the bot will not clear it.")
        assignees = record.get("assignees", [])
        if not assignees or human_only:
            maintainer.append(
                "Use GitHub's **Assignees** picker to assign an available "
                + ("human contributor" if human_only else "contributor")
                + ", or explicitly route the accepted scope to the existing "
                + ("human PR owner" if human_only else "PR owner")
                + ". Acceptance and a merged reference/documentation PR do not assign anyone."
            )
        contributor_role = "Human contributor" if human_only else "Assigned contributor"
        if gated:
            maintainer.append("Resolve the listed acceptance, classification, blocker, or independent routing gates before new implementation dispatch; preserve ongoing work.")
            transition = "Maintainer resolves gates and routes accepted scope → assigned implementation, not delivery."
        elif assignees:
            actor = contributor_role + " (" + ", ".join("@" + assignee["login"] for assignee in assignees) + ")"
            if human_only:
                actor = "Maintainer to confirm human assignment; then human contributor"
            roles[contributor_role] = [
                f"Implement only the accepted scope, run its relevant tests, and open or update the existing linked PR with `Refs #{record['number']}`.",
            ]
            roles["Reviewers"] = ["Review the current PR head using GitHub's native **Review changes** control; required checks and merge controls still apply."]
            transition = "Assigned implementation → native PR review and merge; only a maintainer's actual-fix assessment selects `awaiting-release`."
        else:
            transition = "Maintainer assignment or explicit routing → implementation of the accepted scope."
        maintainer.append("After verifying that the actual fix merged, select `awaiting-release` in GitHub's **Labels** picker; a merged `Refs` link alone is not proof of a fix or delivery.")
    elif stage == "awaiting-release":
        status = "Fix awaiting image delivery" if delivery_type == "image" else f"Fix awaiting {display} application-release delivery"
        if blockers:
            status += " — " + " / ".join(sorted(blockers))
        actor = "Maintainer / release owner"
        roles["Release owner"] = [
            "Verify that the actual fix merged, then track consumption and publication in the reporter's affected "
            + ("image/channel." if delivery_type == "image" else "application installation/channel, including required image-installed helpers."),
            *_delivery_fields(delivery_type),
            "Confirm publication actually reached that installation; a green run with publication skipped is not delivery.",
        ]
        maintainer.append("After checking the recorded delivery evidence, select `needs-verification` using GitHub's **Labels** picker; do not close an unresolved product report at merge.")
        reporter = "No update or verification requested yet; a merged change is not proof the fix reached your installation."
        transition = "Verified publication and authorized `needs-verification` selection → reporter verification."
    elif stage == "needs-verification":
        if not complete_evidence:
            status = "Verification request lacks complete delivery evidence"
            maintainer.extend(_delivery_fields(delivery_type))
            maintainer.append("Verify actual publication, then select `needs-verification` using GitHub's **Labels** picker; do not request an update or close on missing evidence.")
            reporter = "No update or verification requested until a maintainer records complete delivery evidence."
            transition = "Complete authorized delivery evidence → reporter verification request."
        else:
            actor = "Reporter"
            target = (
                f"image `{evidence['image']}`"
                if delivery_type == "image"
                else f"{display} package `{evidence['package']}` version `{evidence['version']}`"
            )
            reporter = "Reply `Confirmed fixed` with the version tested, or `Still broken` with what you observed."
            reporter_steps = [
                f"Update to {target} from [this release/build]({evidence['url']}); reboot if required.",
                evidence["verify"],
            ]
            if delivery_type == "release":
                reporter_steps.append("Follow the recorded installation steps, including any required image-installed helper update.")
            maintainer.append("Retain the delivery evidence; review the reporter's result. Do not treat an unrelated reply or PR merge as confirmation.")
            # The writer anchors instructions to the authorized request event.
            # Reformatting its Verify text must not create a second notification.
            notification_action = _action("verify-delivery", {key: evidence[key] for key in sorted(required - {"verify"})})
            transition = "Reporter `Confirmed fixed` → completed closure; `Still broken` → `needs-triage`."

    if native_gates and not context.get("close"):
        gate_names = " / ".join(f"`{label}`" for label in sorted(native_gates))
        status += f" — human gate: {gate_names}"
        actor += f"; owner of {gate_names} for the recorded human gate"

    links = [
        f"[PR #{pr['number']}]({pr['html_url']})"
        for pr in facts.get("linked_prs", [])
        if not pr.get("merged_at") and pr.get("state") == "open"
    ]
    if links:
        maintainer.append("Preserve existing work: " + ", ".join(links) + "; retain its assignees, branches, reviews, and merge-queue decisions. Route through the existing work owner; do not start a duplicate implementation.")
    notify = bool(notification_action and record.get("user", {}).get("type") == "User")
    if stage == "needs-triage" and not tracking:
        transition = ""
    return {
        "comment": _render(marker, status, actor, transition, roles, reporter, reporter_steps),
        "notify_reporter": notify,
        "notification_action": notification_action if notify else None,
    }


def prow_report(catalog, result):
    """Format actual command outcomes, including recorded partial API changes."""
    outcome = result["outcome"]
    titles = {"applied": "Prow command applied", "denied": "Prow command denied", "invalid": "Prow command invalid or not completed", "help": "Prow command help"}
    if outcome not in titles:
        raise ValueError("Unsupported Prow outcome")
    changes = result.get("changes") or {}
    added, removed = changes.get("add", []), changes.get("remove", [])
    steps = [f"Command: `{result['command']}`."]
    if result.get("reason"):
        steps.append("Result: " + result["reason"])
    if added:
        steps.append("Confirmed added: " + ", ".join(f"`{label}`" for label in added) + ".")
    if removed:
        steps.append("Confirmed removed: " + ", ".join(f"`{label}`" for label in removed) + ".")
    if result.get("changes_unknown"):
        steps.append("The final label state could not be observed; no complete result is confirmed. Inspect GitHub's **Labels** picker before retrying.")
    elif not added and not removed:
        steps.append("No labels changed.")
    elif outcome != "applied":
        steps.append("Only the confirmed changes above occurred; the requested command did not complete. Inspect GitHub's **Labels** picker before retrying.")
    steps.extend(result.get("next_steps") or [])
    if result.get("supported_commands"):
        steps.append("Enabled commands: " + ", ".join(f"`{command}`" for command in result["supported_commands"]) + ".")
    if result.get("pull_request"):
        steps.append("Prow commands are issue-only here. Use GitHub's native **Ready for review**, **Reviewers**, and **Review changes** controls on this PR; required checks and merge controls still apply.")
    else:
        steps.extend([
            "Use only the enabled maintainer commands for descriptive labels or negative hold controls; choose catalog labels in GitHub's **Labels** picker and keep exactly one `kind/*` label.",
            "Implementation acceptance still requires a trusted human to select `triage/accepted` in GitHub's **Labels** picker; Prow does not assign work, clear independent human gates, approve reviews, or merge.",
        ])
    return _render(
        catalog["comment_marker"].replace(" -->", ":prow -->"),
        ("Prow command outcome unconfirmed" if result.get("changes_unknown") else titles[outcome]) + f" — {catalog['display_name']}",
        "Maintainer" if outcome != "help" else "Maintainer seeking command help",
        "Descriptive labels or negative holds only; lifecycle acceptance, native review, delivery, and closure are unchanged.",
        {"Maintainer": steps}, NO_ACTION,
    )
