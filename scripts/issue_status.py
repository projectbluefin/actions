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
    "triage/needs-information": "Waiting for information",
    "triage/accepted": "Accepted",
    "awaiting-release": "Fixed, waiting for release",
    "needs-verification": "Released, waiting for reporter to test",
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
        f"Add {target} under **Delivery evidence** in the issue body.",
        "Also add `Fix revision: <commit>`, `Release/build: <URL>`, and `Verify: <steps>`.",
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
        status, actor = "Draft", "PR contributor"
        roles["PR contributor"] = ["Finish the change and tests, then mark it **Ready for review**."]
        transition = "Ready for review."
    elif pr.get("native_mergeable") == "CONFLICTING":
        status, actor = "Merge conflicts", "PR contributor"
        roles["PR contributor"] = ["Fix the conflicts, rerun tests, and re-request review."]
        transition = "Review."
    elif pr.get("review_decision") == "CHANGES_REQUESTED":
        status, actor = "Changes requested", "PR contributor"
        roles["PR contributor"] = ["Address the feedback, rerun tests, and re-request review."]
        transition = "Review."
    elif pr.get("review_decision") == "APPROVED":
        status = "Approved, waiting on checks and merge"
        actor = "PR contributor; maintainer"
        roles["PR contributor"] = ["Fix any failing checks."]
        roles["Maintainer"] = ["Merge through the merge queue after checks pass."]
        transition = "Merge. Merging is not a release."
    else:
        status, actor = "Waiting for review", "Requested reviewers"
        roles["Requested reviewers"] = ["Review this PR."]
        roles["PR contributor"] = ["Address feedback and re-request review."]
        transition = "Approval or requested changes."
    roles.setdefault("PR contributor", []).append(
        "Use `Refs #NNN` for reports that still need a release, not `Closes #NNN`."
    )
    return {
        "comment": _render(catalog["comment_marker"], status, actor, transition, roles,
                           "No action needed here; reply on the linked issue if asked."),
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
    transition = "Maintainer accepts, asks for information, or closes."
    blockers = labels & {"blocked", "hold"}
    independent_gate = "needs-human" in labels and not context.get("automatic_gate", False)
    native_gates = set(context.get("active_gate_labels", labels & set(catalog.get("gate_labels", [])))) - {"blocked", "hold", "needs-human", "human-only"}
    effective_kind = context.get("kind", {label for label in labels if label.startswith("kind/")})
    kind_missing = not effective_kind
    stale = "triage/accepted" in labels and not approved
    gated = bool(blockers or independent_gate or native_gates or kind_missing or context.get("kind_ambiguous") or not approved)

    if kind_missing or context.get("kind_ambiguous"):
        maintainer.append("Add exactly one `kind/*` label.")
    if stale:
        maintainer.append("Acceptance is out of date. Review the issue, then add `triage/accepted` again.")
    if blockers:
        status += " — " + " / ".join(sorted(blockers))
        actor = "Maintainer / blocker or hold owner"
        roles["Blocker / hold owner"] = [
            "Resolve the blocker, then remove "
            + " and ".join(f"`{label}`" for label in sorted(blockers))
            + ".",
        ]
    if native_gates and not context.get("close"):
        gate_names = " and ".join(f"`{label}`" for label in sorted(native_gates))
        roles["Human gate owner"] = [
            f"Answer the question or decision behind {gate_names}, then remove it.",
            "Acceptance does not remove this gate or assign anyone.",
        ]
    if human_only:
        maintainer.append("Reporter asked for humans only: no AI analysis or agent work.")

    if tracking:
        status = "Tracker, not a work item" + (
            " — " + " / ".join(sorted(blockers)) if blockers else ""
        )
        maintainer.extend([
            "Keep this tracker updated and link child issues.",
            "Accept and assign child issues separately.",
        ])
        transition = "Tracker stays open; child issues move separately."
    elif context.get("close"):
        if stage != "needs-verification" or not complete_evidence:
            raise ValueError("Confirmed closure requires a verification stage and delivery evidence")
        status, actor = "Reporter confirmed the fix", "Lifecycle automation"
        roles["Lifecycle automation"] = ["Close as completed."]
        maintainer.append("Keep the delivery evidence in this issue.")
        transition = "Closed as completed."
        reporter = "No action needed; reopen if the problem returns."
    elif stage == "needs-triage":
        maintainer.extend([
            "To accept, add `triage/accepted`.",
            "Removing `needs-triage` or `needs-human` does not work, let the bot do it.",
            "Accepting means we want it in Bluefin - you are not committed to working on this.",
            "Need more information? Ask, then add `triage/needs-information`. To decline, close with a reason.",
        ])
    elif stage == "triage/needs-information":
        if context.get("requester") == "maintainer" or record.get("user", {}).get("type") != "User":
            status = "Waiting on maintainer decision" + (" — blocked / held" if blockers else "")
            maintainer.extend([
                "Make the decision and update the issue body.",
                "Then remove `needs-decision` and add `triage/accepted`."
                if "needs-decision" in labels else
                "Then add `triage/accepted`.",
            ])
            if missing:
                maintainer.append("Say who can provide: " + ", ".join(f"**{field}**" for field in missing) + ".")
            transition = "Decision made → `triage/accepted`."
        elif missing:
            actor = "Reporter"
            reporter = "Reply with the missing information or update the issue form."
            reporter_steps = [f"Add **{field}**." for field in missing]
            if delivery_type == "image" and "image details" in missing:
                reporter_steps.append("Run `bootc status` and paste the complete output, or say why you can't.")
            elif delivery_type == "release" and any("version" in field.lower() or "application" in field.lower() or "package" in field.lower() for field in missing):
                reporter_steps.append(f"Include your installed {display} version and how you installed it.")
            maintainer.append("Review the reply, then decide whether to accept.")
            notification_action = _action("information-fields", sorted(set(missing)))
            transition = "Reporter replies → maintainer review."
        else:
            request = _request(record, facts, marker, context.get("request_event"))
            if request:
                actor = "Reporter"
                reference = (
                    f"[the maintainer's request]({request['html_url']})"
                    if request.get("html_url") else f"the maintainer's comment #{request['id']}"
                )
                reporter = f"Answer {reference} by replying here."
                maintainer.append("Review the reply before accepting.")
                notification_action = _action("information-comment", request.get("id") or request.get("html_url"))
                transition = "Reporter replies → maintainer review."
            else:
                maintainer.append("Post your question. @mention the reporter only if they need to answer.")
                reporter = "No action needed until a maintainer asks you a question."
                transition = "Question → reply → maintainer review."
    elif stage == "triage/accepted":
        if not approved:
            status = "Acceptance is out of date"
        if independent_gate and not human_only:
            maintainer.append("Someone else added `needs-human`. They remove it when resolved; the bot will not.")
        assignees = record.get("assignees", [])
        if not assignees or human_only:
            maintainer.append(
                "Assign a "
                + ("human contributor" if human_only else "contributor")
                + ", or route this to the existing PR owner."
            )
        contributor_role = "Human contributor" if human_only else "Assigned contributor"
        if gated:
            maintainer.append("Clear the listed blockers before starting work.")
            transition = "Blockers cleared → assign."
        elif assignees:
            actor = contributor_role + " (" + ", ".join("@" + assignee["login"] for assignee in assignees) + ")"
            if human_only:
                actor = "Maintainer to confirm human assignment; then human contributor"
            roles[contributor_role] = [
                f"Implement the accepted scope, test it, and open a PR with `Refs #{record['number']}`.",
            ]
            roles["Reviewers"] = ["Review the PR."]
            transition = "PR review and merge; a maintainer adds `awaiting-release` after the fix merges."
        else:
            transition = "Assign someone → implementation."
        maintainer.append("After the actual fix merges, add `awaiting-release`.")
    elif stage == "awaiting-release":
        status = "Fixed, waiting for image release" if delivery_type == "image" else f"Fixed, waiting for {display} release"
        if blockers:
            status += " — " + " / ".join(sorted(blockers))
        actor = "Maintainer / release owner"
        roles["Release owner"] = [
            "Confirm the fix is published to the affected "
            + ("image." if delivery_type == "image" else "app install, including any image-installed helpers."),
            *_delivery_fields(delivery_type),
        ]
        maintainer.append("Once the fix is published, add `needs-verification`. Keep the report open.")
        reporter = "No action needed yet. Wait for the release."
        transition = "Released → reporter tests it."
    elif stage == "needs-verification":
        if not complete_evidence:
            status = "Missing delivery evidence"
            maintainer.extend(_delivery_fields(delivery_type))
            maintainer.append("Add the evidence, then add `needs-verification`.")
            reporter = "No action needed yet."
            transition = "Evidence added → reporter tests."
        else:
            actor = "Reporter"
            target = (
                f"image `{evidence['image']}`"
                if delivery_type == "image"
                else f"{display} package `{evidence['package']}` version `{evidence['version']}`"
            )
            reporter = "Reply `Confirmed fixed` with the version you tested, or `Still broken` with what you saw."
            reporter_steps = [
                f"Update to {target} from [this release]({evidence['url']}); reboot if needed.",
                evidence["verify"],
            ]
            if delivery_type == "release":
                reporter_steps.append("Follow the install steps, including any image-installed helper update.")
            maintainer.append("Review the reporter's reply.")
            # The writer anchors instructions to the authorized request event.
            # Reformatting its Verify text must not create a second notification.
            notification_action = _action("verify-delivery", {key: evidence[key] for key in sorted(required - {"verify"})})
            transition = "`Confirmed fixed` → closed; `Still broken` → back to triage."

    if native_gates and not context.get("close"):
        gate_names = " / ".join(f"`{label}`" for label in sorted(native_gates))
        status += f" — waiting on {gate_names}"
        actor += f"; owner of {gate_names}"

    links = [
        f"[PR #{pr['number']}]({pr['html_url']})"
        for pr in facts.get("linked_prs", [])
        if not pr.get("merged_at") and pr.get("state") == "open"
    ]
    if links:
        maintainer.append("Existing work: " + ", ".join(links) + ". Don't start a duplicate.")
    notify = bool(notification_action and record.get("user", {}).get("type") == "User")
    if stage == "needs-triage" and not tracking:
        transition = ""
    return {
        "comment": _render(marker, status, actor, transition, roles, reporter, reporter_steps),
        "notify_reporter": notify,
        "notification_action": notification_action if notify else None,
    }


def _code_span(value):
    """Keep untrusted feedback data inside one inert Markdown code span."""
    text = " ".join(str(value).splitlines())
    runs = re.findall(r"`+", text)
    if not runs:
        return f"`{text}`"
    delimiter = "`" * (max(map(len, runs)) + 1)
    return f"{delimiter} {text} {delimiter}"


def prow_report(catalog, result):
    """Format actual command outcomes, including recorded partial API changes."""
    outcome = result["outcome"]
    titles = {"applied": "Command applied", "denied": "Command denied", "invalid": "Command not completed", "help": "Command help"}
    if outcome not in titles:
        raise ValueError("Unsupported Prow outcome")
    changes = result.get("changes") or {}
    added, removed = changes.get("add", []), changes.get("remove", [])
    command = result["command"]
    displayed_command = command[:512] + ("…" if len(command) > 512 else "")
    steps = []
    if outcome != "help":
        steps.append("Command: " + _code_span(displayed_command) + ".")
        if result.get("reason"):
            steps.append("Result: " + result["reason"])
        if added:
            steps.append("Added: " + ", ".join(_code_span(label) for label in added) + ".")
        if removed:
            steps.append("Removed: " + ", ".join(_code_span(label) for label in removed) + ".")
        if result.get("changes_unknown"):
            steps.append("Could not confirm the final labels. Check the issue labels before retrying.")
        elif not added and not removed:
            steps.append("No labels changed.")
        elif outcome != "applied":
            steps.append("Only the changes above happened. Check the labels before retrying.")
        steps.extend(result.get("next_steps") or [])
    if result.get("supported_commands") and outcome != "applied":
        steps.append("Commands: " + ", ".join(_code_span(command) for command in result["supported_commands"]) + ".")
    if result.get("pull_request"):
        steps.append("Commands only work on issues. Use the PR's normal review and merge controls.")
    else:
        steps.append("Prow only sets kind/area or pauses issues. To accept work, add `triage/accepted`.")
    return _render(
        catalog["comment_marker"].replace(" -->", ":prow -->"),
        ("Command result unconfirmed" if result.get("changes_unknown") else titles[outcome]) + f" — {catalog['display_name']}",
        "Maintainer",
        "",
        {"Maintainer": steps}, NO_ACTION,
    )
