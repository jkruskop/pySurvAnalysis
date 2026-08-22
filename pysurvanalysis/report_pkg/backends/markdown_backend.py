"""Markdown renderer for the block model.

The second backend exists so ``report.md`` can never drift from the PDF: both
walk the same blocks, so a section added to the builder appears in both without
anyone remembering to update a string template. Figures are written next to the
markdown file and linked relatively, which keeps the file diffable in git —
base64-inlining them would make every re-run a whole-file change.
"""

from __future__ import annotations

from pathlib import Path

from .. import model as m

_LEVEL_MARK = {
    m.Level.OK: "✅",
    m.Level.WARN: "⚠️",
    m.Level.ERROR: "❌",
    m.Level.NEUTRAL: "",
}


def _escape(text: str) -> str:
    return str(text).replace("|", "\\|")


def _table(block: m.Table) -> list[str]:
    out: list[str] = []
    if block.title:
        out.append(f"**{block.title}**")
        out.append("")
    if not block.columns:
        return out
    out.append("| " + " | ".join(_escape(c) for c in block.columns) + " |")
    out.append("|" + "|".join("---" for _ in block.columns) + "|")
    levels = list(block.row_levels) + [None] * len(block.rows)
    for row, level in zip(block.rows, levels):
        cells = [_escape(c) for c in row]
        mark = _LEVEL_MARK.get(level, "") if level else ""
        if mark and cells:
            cells[0] = f"{mark} {cells[0]}"
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    if block.caption:
        out.append(f"*{block.caption}*")
        out.append("")
    return out


def render(report: m.Report, path: str) -> str:
    """Write *report* as markdown, saving figures beside it."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    assets = target.parent / f"{target.stem}_figures"

    lines: list[str] = []
    fig_index = 0

    for block in report.blocks:
        if isinstance(block, m.Cover):
            lines.append(f"# {block.title}")
            lines.append("")
            if block.subtitle:
                lines.append(f"*{block.subtitle}*")
                lines.append("")
            for label, value in block.metadata:
                lines.append(f"- **{label}:** {value}")
            if block.metadata:
                lines.append("")
            for status in block.status_lines():
                mark = _LEVEL_MARK.get(status.level, "")
                lines.append(f"> {mark} {status.text}".strip())
                lines.append("")
        elif isinstance(block, m.SectionDivider):
            lines.append(f"## {block.title}")
            lines.append("")
            if block.subtitle:
                lines.append(block.subtitle)
                lines.append("")
        elif isinstance(block, m.Heading):
            lines.append(f"{'#' * min(block.level + 2, 6)} {block.text}")
            lines.append("")
        elif isinstance(block, m.Paragraph):
            lines.append(block.text)
            lines.append("")
        elif isinstance(block, m.Preformatted):
            if block.title:
                lines.append(f"**{block.title}**")
                lines.append("")
            lines.append("```")
            lines.append(block.text)
            lines.append("```")
            lines.append("")
        elif isinstance(block, m.Table):
            lines.extend(_table(block))
        elif isinstance(block, m.Figure):
            fig_index += 1
            assets.mkdir(parents=True, exist_ok=True)
            name = f"figure_{fig_index:02d}.{block.fmt}"
            (assets / name).write_bytes(block.data)
            alt = block.title or f"Figure {fig_index}"
            lines.append(f"### {alt}" if block.title else "")
            lines.append(f"![{alt}]({assets.name}/{name})")
            lines.append("")
            if block.caption:
                lines.append(f"*{block.caption}*")
                lines.append("")
        elif isinstance(block, m.PageBreak):
            lines.append("---")
            lines.append("")

    text = "\n".join(line for line in lines if line is not None)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")
    return str(target)
