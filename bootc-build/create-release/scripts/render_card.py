#!/usr/bin/env python3
"""
render_card.py — Generate a release card PNG from versions.json.

Usage:
    python3 render_card.py \\
        --versions      versions.json \\
        --tag           2026-05-14-abc1234 \\
        --date          2026-05-14 \\
        --sha7          abc1234 \\
        --project-name  "Bluefin" \\
        --accent-color  "#0ea5e9" \\
        --badge-label   "Stable" \\
        --image-ref     "ghcr.io/projectbluefin/bluefin" \\
        --docs-url      "https://docs.projectbluefin.io/changelogs" \\
        --output        release-card.png
"""
import argparse
import html
import json
import os
import tempfile


# ── HTML card template ────────────────────────────────────────────────────────
# Self-contained: no external resources, no web fonts.
# Accent colour, project name, badge label, and image ref are injected at
# render time so the same script serves bluefin, bluefin-lts, and dakota.
# Rendered at 840 px wide; Playwright crops to the .release-card bounding box.

_CARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=840">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

/* ── Light theme ── */
:root {{
  --bg:             #ffffff;
  --bg-card:        #f9fafb;
  --border:         #e5e7eb;
  --accent:         {accent_color};
  --accent-faint:   color-mix(in srgb, {accent_color} 12%, transparent);
  --accent-mid:     color-mix(in srgb, {accent_color} 40%, transparent);
  --text:           #111827;
  --text-muted:     #6b7280;
  --chip-bg:        #f3f4f6;
  --chip-label:     #6b7280;
  --chip-val:       #111827;
  --changed-bg:     color-mix(in srgb, {accent_color} 8%, #fff);
  --changed-border: color-mix(in srgb, {accent_color} 50%, transparent);
  --changed-val:    {accent_color};
  --diff-add:       #059669;
  --diff-chg:       {accent_color};
  --diff-rem:       #dc2626;
  --tag-bg:         #f3f4f6;
}}
/* ── Dark theme ── */
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg:             #0f172a;
    --bg-card:        #1e293b;
    --border:         #334155;
    --accent:         color-mix(in srgb, {accent_color} 80%, #fff);
    --accent-faint:   color-mix(in srgb, {accent_color} 15%, transparent);
    --accent-mid:     color-mix(in srgb, {accent_color} 35%, transparent);
    --text:           #f1f5f9;
    --text-muted:     #94a3b8;
    --chip-bg:        #334155;
    --chip-label:     #94a3b8;
    --chip-val:       #f1f5f9;
    --changed-bg:     color-mix(in srgb, {accent_color} 18%, #0f172a);
    --changed-border: color-mix(in srgb, {accent_color} 60%, transparent);
    --changed-val:    color-mix(in srgb, {accent_color} 80%, #fff);
    --diff-add:       #34d399;
    --diff-chg:       color-mix(in srgb, {accent_color} 80%, #fff);
    --diff-rem:       #f87171;
    --tag-bg:         #1e293b;
  }}
}}

body {{
  background: var(--bg);
  padding: 16px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               Helvetica, Arial, sans-serif;
}}

.release-card {{
  background:    var(--bg-card);
  border:        1px solid var(--border);
  border-left:   3px solid var(--accent);
  border-radius: 12px;
  padding:       20px 24px 16px;
  max-width:     800px;
}}

/* ── Header ── */
.card-header {{
  display:         flex;
  align-items:     flex-start;
  justify-content: space-between;
  margin-bottom:   14px;
}}
.card-title {{
  font-size:    1.25rem;
  font-weight:  700;
  color:        var(--accent);
  margin-bottom: 4px;
}}
.card-meta {{
  display:     flex;
  align-items: center;
  gap:         10px;
  flex-wrap:   wrap;
}}
.card-tag {{
  font-family:  "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size:    0.8rem;
  color:        var(--text-muted);
  background:   var(--tag-bg);
  padding:      2px 8px;
  border-radius: 6px;
}}
.card-date {{ font-size: 0.8rem; color: var(--text-muted); }}
.card-badge {{
  font-size:      0.65rem;
  font-weight:    700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding:        2px 9px;
  border-radius:  999px;
  background:     var(--accent-faint);
  color:          var(--accent);
  border:         1px solid var(--accent-mid);
}}

/* ── Version chips ── */
.chips-row {{
  display:       flex;
  flex-wrap:     wrap;
  gap:           6px;
  margin-bottom: 12px;
}}
.chip {{
  display:       inline-flex;
  align-items:   center;
  border-radius: 6px;
  overflow:      hidden;
  border:        1px solid var(--border);
  font-size:     0.78rem;
  line-height:   1;
}}
.chip.changed {{
  border-color: var(--changed-border);
  background:   var(--changed-bg);
}}
.chip-label {{
  background:  var(--chip-bg);
  color:       var(--chip-label);
  padding:     5px 7px;
  font-weight: 500;
}}
.chip-value {{
  color:       var(--chip-val);
  padding:     5px 7px;
  font-weight: 600;
}}
.chip.changed .chip-value {{ color: var(--changed-val); }}
.chip-prev {{
  color:           var(--text-muted);
  font-size:       0.72rem;
  padding:         5px 6px 5px 0;
  text-decoration: line-through;
}}
.chip-arrow {{
  color:       var(--accent);
  padding:     5px 3px 5px 0;
  font-size:   0.65rem;
  font-weight: 700;
}}

/* ── Diff bar ── */
.diff-bar {{
  display:       flex;
  gap:           14px;
  font-size:     0.8rem;
  color:         var(--text-muted);
  margin-bottom: 12px;
  padding:       8px 12px;
  background:    var(--chip-bg);
  border-radius: 8px;
}}
.diff-changed {{ color: var(--diff-chg); font-weight: 600; }}
.diff-added   {{ color: var(--diff-add); font-weight: 600; }}
.diff-removed {{ color: var(--diff-rem); font-weight: 600; }}

/* ── Footer ── */
.card-footer {{
  display:         flex;
  align-items:     center;
  justify-content: space-between;
  margin-top:      10px;
  padding-top:     10px;
  border-top:      1px solid var(--border);
  font-size:       0.78rem;
  color:           var(--text-muted);
}}
.card-footer a {{ color: var(--accent); text-decoration: none; font-weight: 500; }}
.image-ref {{
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size:   0.72rem;
}}
</style>
</head>
<body>
<div class="release-card">
  <div class="card-header">
    <div>
      <div class="card-title">{project_name}</div>
      <div class="card-meta">
        <span class="card-tag">{tag}</span>
        <span class="card-date">{date_long}</span>
        <span class="card-badge">{badge_label}</span>
      </div>
    </div>
  </div>
  <div class="chips-row">
{chips_html}
  </div>
{diff_bar_html}
  <div class="card-footer">
    <span class="image-ref">{image_ref}:{sha7}</span>
    <a href="{docs_url}">{docs_url_short} →</a>
  </div>
</div>
</body>
</html>
"""


# ── Rendering helpers ─────────────────────────────────────────────────────────

def _chip(pkg: dict) -> str:
    label   = pkg["name"]
    version = pkg["version"]
    prev    = pkg.get("prev")
    changed = pkg.get("changed", False)

    cls        = ' class="chip changed"' if changed else ' class="chip"'
    prev_html  = ""
    arrow_html = ""
    if changed and prev:
        prev_html  = f'      <span class="chip-prev">{html.escape(prev)}</span>\n'
        arrow_html = '      <span class="chip-arrow">↑</span>\n'

    return (
        f'    <span{cls}>\n'
        f'      <span class="chip-label">{html.escape(label)}</span>\n'
        f'{prev_html}'
        f'{arrow_html}'
        f'      <span class="chip-value">{html.escape(version)}</span>\n'
        f'    </span>'
    )


def _diff_bar(diff: dict, has_prev: bool) -> str:
    if not has_prev:
        return ""
    parts = []
    if diff["changed_count"]:
        parts.append(f'<span class="diff-changed">↑ {diff["changed_count"]} updated</span>')
    if diff["added_count"]:
        parts.append(f'<span class="diff-added">+ {diff["added_count"]} added</span>')
    if diff["removed_count"]:
        parts.append(f'<span class="diff-removed">− {diff["removed_count"]} removed</span>')
    if not parts:
        parts.append("<span>No package changes since last release</span>")
    return '  <div class="diff-bar">\n    ' + "\n    ".join(parts) + "\n  </div>\n"


def _build_html(
    versions: dict,
    *,
    tag: str,
    date: str,
    sha7: str,
    project_name: str,
    accent_color: str,
    badge_label: str,
    image_ref: str,
    docs_url: str,
) -> str:
    from datetime import datetime
    dt        = datetime.strptime(date, "%Y-%m-%d")
    date_long = dt.strftime("%B %-d, %Y")

    # Strip protocol for footer display
    docs_url_short = docs_url.removeprefix("https://").removeprefix("http://")

    chips_html   = "\n".join(_chip(p) for p in versions["notable"])
    diff_bar_html = _diff_bar(versions["diff"], versions["has_prev"])

    return _CARD_HTML.format(
        project_name=html.escape(project_name),
        accent_color=accent_color,
        badge_label=html.escape(badge_label),
        tag=html.escape(tag),
        date_long=html.escape(date_long),
        sha7=html.escape(sha7),
        image_ref=html.escape(image_ref),
        docs_url=html.escape(docs_url),
        docs_url_short=html.escape(docs_url_short),
        chips_html=chips_html,
        diff_bar_html=diff_bar_html,
    )


def _screenshot(html_path: str, output_path: str, color_scheme: str = "light") -> None:  # pragma: no cover
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 840, "height": 600},
            device_scale_factor=2,
            color_scheme=color_scheme,
        )
        page = ctx.new_page()
        page.goto(f"file://{os.path.abspath(html_path)}")
        page.wait_for_load_state("networkidle")
        page.locator(".release-card").first.screenshot(path=output_path)
        browser.close()
    print(f"  {color_scheme}: {output_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:  # pragma: no cover
    ap = argparse.ArgumentParser(description="Render a Bluefin release card")
    ap.add_argument("--versions",      required=True, help="Path to _versions.json")
    ap.add_argument("--tag",           required=True, help="Release tag, e.g. lts-20260612")
    ap.add_argument("--date",          required=True, help="YYYY-MM-DD")
    ap.add_argument("--sha7",          required=True)
    ap.add_argument("--project-name",  default="Bluefin")
    ap.add_argument("--accent-color",  default="#0ea5e9")
    ap.add_argument("--badge-label",   default="Stable")
    ap.add_argument("--image-ref",     required=True,
                    help="Full image ref without tag, e.g. ghcr.io/projectbluefin/bluefin")
    ap.add_argument("--docs-url",      default="https://docs.projectbluefin.io/changelogs")
    ap.add_argument("--output",        default="release-card.png",
                    help="Output PNG path (light theme). Dark variant saved as *-dark.png")
    args = ap.parse_args()

    with open(args.versions, encoding="utf-8") as f:
        versions = json.load(f)

    card_html = _build_html(
        versions,
        tag=args.tag,
        date=args.date,
        sha7=args.sha7,
        project_name=args.project_name,
        accent_color=args.accent_color,
        badge_label=args.badge_label,
        image_ref=args.image_ref,
        docs_url=args.docs_url,
    )

    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", delete=False, dir=".", encoding="utf-8"
    ) as tmp:
        tmp.write(card_html)
        html_path = tmp.name

    try:
        print("Rendering release card...")
        stem, ext = os.path.splitext(args.output)
        _screenshot(html_path, args.output,          color_scheme="light")
        _screenshot(html_path, f"{stem}-dark{ext}",  color_scheme="dark")
    finally:
        os.unlink(html_path)


if __name__ == "__main__":  # pragma: no cover
    main()
