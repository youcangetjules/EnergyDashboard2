"""
Energy Dashboard — Bug Tracker tab (Controls group).

Shows the standing defect log from the repo-root ``bug_tracker.md`` file
(open bugs first, then fixed — newest first within each section).
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from energy_dashboard.common import *

_BUG_TRACKER_PATH = Path(__file__).resolve().parents[2] / "bug_tracker.md"


def _md_inline(text: str) -> str:
    """Escape HTML then apply a few markdown inline rules used in bug_tracker.md."""
    s = html.escape(text)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        s,
    )
    return s


def bug_tracker_md_to_html(md: str) -> str:
    """Lightweight markdown→HTML for the bug tracker file (no extra deps)."""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    in_code = False
    code_buf: list[str] = []

    def flush_code():
        nonlocal code_buf
        if not code_buf:
            return
        body = html.escape("\n".join(code_buf))
        out.append(
            "<pre style='margin:8px 0; padding:10px; background:#181825; "
            "border:1px solid #313244; border-radius:4px; "
            f"white-space:pre-wrap;'>{body}</pre>"
        )
        code_buf = []

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if line.startswith("|") and i + 1 < len(lines) and re.match(
            r"^\|\s*[-:]+", lines[i + 1] or ""
        ):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].startswith("|"):
                raw = lines[i].strip()
                if re.match(r"^\|\s*[-:| ]+\|$", raw):
                    i += 1
                    continue
                cells = [c.strip() for c in raw.strip("|").split("|")]
                rows.append(cells)
                i += 1
            if rows:
                out.append(
                    "<table style='border-collapse:collapse; margin:6px 0 12px 0;'>"
                )
                for r_i, cells in enumerate(rows):
                    out.append("<tr>")
                    tag = "th" if r_i == 0 else "td"
                    for cell in cells:
                        out.append(
                            f"<{tag} style='border:1px solid #45475a; padding:4px 10px; "
                            f"text-align:left;'>{_md_inline(cell)}</{tag}>"
                        )
                    out.append("</tr>")
                out.append("</table>")
            continue

        if line.strip() == "---":
            out.append("<hr style='border:none; border-top:1px solid #45475a; margin:14px 0;'>")
            i += 1
            continue

        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            text = _md_inline(m.group(2).strip())
            sizes = {1: "18px", 2: "15px", 3: "13px"}
            margins = {1: "0 0 10px 0", 2: "16px 0 8px 0", 3: "14px 0 6px 0"}
            out.append(
                f"<h{level} style='margin:{margins[level]}; font-size:{sizes[level]}; "
                f"color:#cdd6f4;'>{text}</h{level}>"
            )
            i += 1
            continue

        if re.match(r"^\d+\.\s+", line) or line.startswith("- "):
            items: list[str] = []
            ordered = bool(re.match(r"^\d+\.\s+", line))
            while i < len(lines) and (
                (ordered and re.match(r"^\d+\.\s+", lines[i]))
                or (not ordered and lines[i].startswith("- "))
            ):
                item = re.sub(r"^(\d+\.\s+|- )", "", lines[i])
                items.append(f"<li style='margin:2px 0;'>{_md_inline(item)}</li>")
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(
                f"<{tag} style='margin:6px 0 10px 18px; padding:0;'>"
                + "".join(items)
                + f"</{tag}>"
            )
            continue

        if not line.strip():
            i += 1
            continue

        # Paragraph: gather consecutive non-blank, non-special lines.
        paras: list[str] = []
        while i < len(lines):
            ln = lines[i]
            if (
                not ln.strip()
                or ln.startswith("#")
                or ln.startswith("|")
                or ln.strip() == "---"
                or ln.startswith("- ")
                or re.match(r"^\d+\.\s+", ln)
                or ln.strip().startswith("```")
            ):
                break
            paras.append(ln.strip())
            i += 1
        if paras:
            out.append(
                "<p style='margin:0 0 8px 0; line-height:1.45;'>"
                + _md_inline(" ".join(paras))
                + "</p>"
            )

    if in_code:
        flush_code()

    style = (
        "body { font-family: Helvetica, Arial, sans-serif; font-size: 12px; "
        "color: #cdd6f4; }"
        "code { background: #313244; padding: 1px 4px; border-radius: 3px; "
        "font-size: 11px; }"
        "a { color: #89b4fa; }"
        "b { color: #e2e8f0; }"
    )
    return f"<html><head><style>{style}</style></head><body>{''.join(out)}</body></html>"


class BugTrackerTab(QWidget):
    """Read-only view of the project ``bug_tracker.md`` defect log."""

    def __init__(self, dash=None):
        super().__init__()
        self.dash = dash
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Bug Tracker")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4;")
        head.addWidget(title)
        head.addStretch(1)
        self.path_lbl = QLabel()
        self.path_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(self.path_lbl)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setFixedWidth(110)
        self.reload_btn.setToolTip("Re-read bug_tracker.md from disk")
        self.reload_btn.clicked.connect(self.reload)
        head.addWidget(self.reload_btn)
        layout.addLayout(head)

        hint = QLabel(
            "Standing log of every defect that affects the app — open bugs first, "
            "then fixed (newest first). Agents and people update "
            "<code>bug_tracker.md</code> at the project root; this tab only displays it."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(hint)

        self.body = QTextBrowser(self)
        self.body.setOpenExternalLinks(True)
        self.body.setStyleSheet(
            f"QTextBrowser {{ background: {_DARK_SURFACE_BG}; color: #cdd6f4; "
            "border: 1px solid #313244; border-radius: 4px; }"
        )
        layout.addWidget(self.body, 1)

        self.reload()

    def showEvent(self, event):
        super().showEvent(event)
        # Pick up agent edits without requiring a click every time.
        self.reload()

    def reload(self) -> None:
        path = _BUG_TRACKER_PATH
        self.path_lbl.setText(str(path))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.body.setHtml(
                "<p style='color:#f38ba8;'><b>Could not read bug tracker</b><br>"
                f"{html.escape(str(exc))}</p>"
            )
            return
        self.body.setHtml(bug_tracker_md_to_html(text))


__all__ = ["BugTrackerTab", "bug_tracker_md_to_html", "_BUG_TRACKER_PATH"]
