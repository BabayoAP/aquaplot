"""The thing a citizen actually sends to a water authority (FR-12).

Every serious finding in `onehealth.py` ends in some version of "report it". Until
now the app produced nothing to report *with*, which left a volunteer to
paraphrase a dashboard into a contact form from memory — and a paraphrase is
exactly the kind of evidence an agency can dismiss.

So this module renders one assessment as a complete, self-contained incident
report: what was observed, when, at what coordinates, by what method, what the
index says, what the rules concluded, what is being asked for, and what the
limits of the evidence are. It is written to be **forwarded without editing** and
read by someone who has never heard of AquaPlot.

Three things shape the wording:

* **Lead with the ask.** An environmental-health officer triages by what is being
  requested, not by what was found, so the request comes first and the evidence
  supports it.
* **State the limits in the report itself**, not in a footnote nobody forwards. A
  screening reading that oversells itself is worse than no reading: it costs the
  next volunteer their credibility too.
* **Separate what a person saw from what a model proposed.** Every habitat line is
  attributed, and the count of human-confirmed observations is stated up front.
  An agency is entitled to know which half of the evidence had eyes on it.

The same content renders as Markdown (for pasting into a form or an email) and as
a printable HTML page (for attaching as a PDF). The Markdown is the source of
truth; the HTML wraps it.
"""

from __future__ import annotations

import html
import re
from typing import Any

from .assess import Assessment
from .bioindex import Band
from .onehealth import DISCLAIMER, Level

# What a report is *for*, by the worst finding in it. An officer triages on this
# line, so it is the first sentence in the document.
REQUEST_BY_LEVEL: dict[Level, str] = {
    Level.ALERT: (
        "**Requesting investigation.** A citizen assessment at this location recorded conditions "
        "with a direct exposure pathway to people or animals. The observations below were confirmed "
        "on site by the observer."
    ),
    Level.CONCERN: (
        "**Requesting review.** A citizen assessment at this location recorded conditions that "
        "suggest a persistent pressure on this watercourse."
    ),
    Level.WATCH: (
        "**For your records.** A citizen assessment at this location recorded early signs worth "
        "tracking, but nothing that calls for immediate action."
    ),
    Level.OK: (
        "**For your records.** A citizen assessment at this location found the watercourse in good "
        "condition. Baseline records matter as much as incident reports: they are what a later "
        "decline is measured against."
    ),
}

# Each line completes the sentence "Screening class: <Band> — ...", so none of
# them repeats the band name.
BAND_LINE: dict[Band, str] = {
    Band.HIGH: "the community is dominated by pollution-sensitive taxa.",
    Band.GOOD: "sensitive taxa present alongside tolerant ones.",
    Band.MODERATE: "sensitive taxa reduced.",
    Band.POOR: "community dominated by pollution-tolerant taxa.",
    Band.BAD: "only taxa tolerant of severe oxygen depletion recorded.",
}


def _coords(a: Assessment) -> str:
    if a.region.lat is None or a.region.lon is None:
        return "not recorded"
    return f"{a.region.lat:.5f}, {a.region.lon:.5f} (WGS84)"


def _map_link(a: Assessment) -> str | None:
    if a.region.lat is None or a.region.lon is None:
        return None
    return f"https://www.openstreetmap.org/?mlat={a.region.lat:.5f}&mlon={a.region.lon:.5f}#map=17/{a.region.lat:.5f}/{a.region.lon:.5f}"


def markdown(a: Assessment, site_history: list[dict[str, Any]] | None = None) -> str:
    """The report as Markdown, ready to paste into a contact form or an email."""
    lines: list[str] = []
    site = a.site_name or (a.region.place.display_name if a.region.place else "Unnamed watercourse")
    worst = a.signal.worst

    lines += [
        f"# Watercourse condition report — {site}",
        "",
        REQUEST_BY_LEVEL[worst],
        "",
        "## Location and time",
        "",
        f"- **Site:** {site}",
        f"- **Coordinates:** {_coords(a)}",
    ]
    if a.region.place is not None:
        lines.append(f"- **Administrative area:** {a.region.place.display_name}")
    link = _map_link(a)
    if link:
        lines.append(f"- **Map:** {link}")
    lines += [
        f"- **Observed:** {a.created_at}",
        f"- **Photographs taken:** {a.photos}",
        f"- **Reference:** AquaPlot assessment `{a.id}` ({a.version})",
        "",
        "## What is being reported",
        "",
    ]

    serious = [f for f in a.signal.findings if f.level.rank >= Level.CONCERN.rank]
    if serious:
        for f in serious:
            lines.append(f"### {f.title}  \n*{f.domain.value} health — {f.level.value}*")
            lines.append("")
            lines += [f"- {b}" for b in f.because]
            lines.append("")
            lines.append(f"**Action the observer was advised to take:** {f.action}")
            lines.append("")
    else:
        lines += ["No finding at concern level or above. This report is a baseline record.", ""]

    lines += [
        "## Biological condition",
        "",
        f"- **Screening class:** {a.ecology.band.value} — {BAND_LINE[a.ecology.band]}",
        f"- **Index:** {a.ecology.index.total} {a.ecology.bmwp:.0f}"
        + (f", {a.ecology.index.mean} {a.ecology.aspt:.2f}" if a.ecology.aspt is not None else f", {a.ecology.index.mean} not calculable")
        + f", {a.ecology.families} scoring families, {a.ecology.ept_families} EPT families",
    ]
    if a.ecology.evidence_limited:
        lines.append("- **Note:** the sample was too small to support a firmer class; treat as provisional.")
    lines.append("")
    if a.ecology.scored or a.ecology.recorded:
        lines += [f"| Taxon recorded | {a.ecology.index.total} | Sensitivity | Identified by |", "|---|---|---|---|"]
        for t in a.ecology.scored:
            who = "observer (confirmed)" if t.confirmed else "model, unconfirmed"
            level = t.family or f"{t.group} (order only)"
            lines.append(f"| {level} | {t.score:.0f} | {t.sensitivity} | {who} |")
        for t in a.ecology.recorded:
            who = "observer (confirmed)" if t.confirmed else "model, unconfirmed"
            lines.append(f"| {t.family or t.group} | not scored | not scored by {a.ecology.index.total} | {who} |")
        lines.append("")
    if a.second_opinion is not None:
        lines += [f"**Independent check:** {a.second_opinion.summary()}", ""]
    for signal in a.ecology.signals:
        lines.append(f"> {signal}")
        lines.append("")

    scoreable = a.pressures.as_dict()["of"]
    lines += [
        "## Visual site assessment",
        "",
        f"Pressure index {a.pressures.pressure:.0f}/100 ({a.pressures.band}), "
        f"from {a.pressures.answered} of {scoreable} scoreable indicators answered.",
        "",
        "| Indicator | Recorded as | Reported by |",
        "|---|---|---|",
    ]
    for r in (*a.pressures.readings, *a.pressures.exposure):
        lines.append(f"| {r.question.rstrip('?')} | {r.label} | {r.source} |")
    lines.append("")

    if a.invasives:
        lines += ["## Invasive species recorded", ""]
        for i in a.invasives:
            d = i.as_dict()
            lines.append(f"- **{d['name']}** — listed by {d['source']} ({d['scope']}). {d['why_it_matters']}")
        lines.append("")

    if site_history and len(site_history) > 1:
        lines += ["## Previous assessments at this site", "", "| Date | Class | Pressure | Overall |", "|---|---|---|---|"]
        for row in site_history[:8]:
            lines.append(
                f"| {row['created_at'][:10]} | {row['band']} | {row['pressure']:.0f}/100 | {row['overall_level']} |"
            )
        lines += ["", "A series at one location is stronger evidence than any single visit.", ""]

    lines += [
        "## Requested next steps",
        "",
    ]
    asks = a.signal.actions_authority or [
        "No specific action requested. Please retain this record as a baseline for this reach."
    ]
    lines += [f"{n}. {ask}" for n, ask in enumerate(asks, 1)]
    lines += [
        "",
        "## How this reading was produced, and what it is not",
        "",
        f"- Method: {a.ecology.index.name} family-level screening ({a.ecology.index.citation}) from citizen "
        "photographs and a structured visual site form.",
        f"- Observations confirmed on site by the observer: **{a.confirmations}**. "
        f"Automated observations were produced by `{a.observer}` and are marked unconfirmed in the tables above.",
        f"- Assessment certainty as evidenced: **{a.certainty:.0f}%**.",
        f"- {a.ecology.caveat}",
        f"- {DISCLAIMER}",
    ]
    if a.penalties:
        lines += ["", "**Stated limitations of this assessment:**", ""]
        lines += [f"- {p}" for p in a.penalties]
    lines += [
        "",
        "---",
        "",
        f"Generated by AquaPlot ({a.version}). Bioindicator catalogue `{a.ecology.catalogue_version}`, "
        f"site form `{a.pressures.form_version}`. A machine-readable FHIR R4 version of this assessment "
        f"is available at `/api/assess/{a.id}/fhir`.",
    ]
    return "\n".join(lines)


# ---- a printable page --------------------------------------------------------

_INLINE = (
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])"), r"<em>\1</em>"),
    (re.compile(r"`(.+?)`"), r"<code>\1</code>"),
    (re.compile(r"(?<!\()\bhttps?://[^\s<)]+"), lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>'),
)


def _inline(text: str) -> str:
    out = html.escape(text)
    for pattern, repl in _INLINE:
        out = pattern.sub(repl, out)
    return out.replace("  \n", "<br>")


def _render_blocks(md: str) -> str:
    """A deliberately small Markdown subset: the headings, lists, tables and quotes
    this module emits, and nothing else. A general Markdown library would be a
    dependency added for one page that only ever renders our own output."""
    out: list[str] = []
    rows: list[str] = []
    bullets: list[str] = []
    numbers: list[str] = []

    def flush() -> None:
        nonlocal rows, bullets, numbers
        if rows:
            header, *body = [r for r in rows if not set(r.replace("|", "").strip()) <= {"-", " ", ":"}]
            cells = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells(header)) + "</tr></thead><tbody>")
            for r in body:
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells(r)) + "</tr>")
            out.append("</tbody></table>")
            rows = []
        if bullets:
            out.append("<ul>" + "".join(f"<li>{_inline(b)}</li>" for b in bullets) + "</ul>")
            bullets = []
        if numbers:
            out.append("<ol>" + "".join(f"<li>{_inline(b)}</li>" for b in numbers) + "</ol>")
            numbers = []

    for raw in md.split("\n"):
        line = raw.rstrip()
        if line.startswith("|"):
            rows.append(line)
            continue
        if line.startswith("- "):
            bullets.append(line[2:])
            continue
        if re.match(r"^\d+\. ", line):
            numbers.append(line.split(". ", 1)[1])
            continue
        flush()
        if not line:
            continue
        if line.startswith("### "):
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
        elif line.startswith("---"):
            out.append("<hr>")
        else:
            out.append(f"<p>{_inline(line)}</p>")
    flush()
    return "\n".join(out)


PRINT_CSS = """
:root { color-scheme: light; }
body { max-width: 46em; margin: 0 auto; padding: 32px 20px 64px; background: #fff; color: #111;
       font: 15px/1.6 Georgia, "Iowan Old Style", "Times New Roman", serif; }
h1 { font-size: 24px; line-height: 1.25; margin: 0 0 6px; }
h2 { font-size: 17px; margin: 28px 0 8px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
h3 { font-size: 15px; margin: 18px 0 4px; }
p, li { margin: 6px 0; }
em { color: #555; }
code { font: 13px ui-monospace, Menlo, monospace; background: #f3f3f3; padding: 1px 4px; border-radius: 3px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13.5px; font-family: system-ui, sans-serif; }
th, td { border: 1px solid #ddd; padding: 5px 8px; text-align: left; vertical-align: top; }
th { background: #f5f5f5; }
blockquote { margin: 10px 0; padding: 8px 14px; border-left: 3px solid #bbb; background: #fafafa; color: #333; }
hr { border: 0; border-top: 1px solid #ddd; margin: 28px 0 12px; }
a { color: #0f6b7a; }
.toolbar { font-family: system-ui, sans-serif; font-size: 14px; background: #eef4f5; border: 1px solid #cfe0e3;
           border-radius: 8px; padding: 10px 14px; margin-bottom: 24px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.toolbar button { font: inherit; font-weight: 600; cursor: pointer; border: 1px solid #0f6b7a; background: #0f6b7a;
                  color: #fff; border-radius: 6px; padding: 7px 13px; }
.toolbar button.ghost { background: transparent; color: #0f6b7a; }
.toolbar span { color: #44606a; }
@media print { .toolbar { display: none; } body { padding: 0; } }
"""


def as_page(title: str, md: str, toolbar: str = "") -> str:
    """Wrap any of our own Markdown in the same self-contained printable page.

    Used for the field guide as well as the report, so a community group printing
    the sampling protocol gets the same typography as the document they will later
    send to their water authority.
    """
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{PRINT_CSS}</style></head>
<body>
<div class="toolbar">
  <button onclick="window.print()">Print or save as PDF</button>
  {toolbar}
  <a href="/">Back to AquaPlot</a>
</div>
{_render_blocks(md)}
</body></html>"""


def printable(a: Assessment, site_history: list[dict[str, Any]] | None = None) -> str:
    """The same report as a self-contained page: print it, or save it as a PDF."""
    md = markdown(a, site_history)
    title = a.site_name or (a.region.place.display_name if a.region.place else "Watercourse condition report")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Condition report — {html.escape(title)}</title>
<style>{PRINT_CSS}</style></head>
<body>
<div class="toolbar">
  <button onclick="window.print()">Print or save as PDF</button>
  <button class="ghost" id="copy">Copy as text</button>
  <a href="/api/assess/{a.id}/report.md">Download Markdown</a>
  <span>Send this to your water authority or environmental regulator.</span>
</div>
{_render_blocks(md)}
<script>
const SOURCE = {_json_literal(md)};
document.getElementById("copy").addEventListener("click", async () => {{
  try {{ await navigator.clipboard.writeText(SOURCE); document.getElementById("copy").textContent = "Copied"; }}
  catch (e) {{ alert("Copy failed; use Download Markdown instead."); }}
}});
</script>
</body></html>"""


def _json_literal(text: str) -> str:
    import json

    # </script> inside a JS string literal would end the block early.
    return json.dumps(text).replace("</", "<\\/")
