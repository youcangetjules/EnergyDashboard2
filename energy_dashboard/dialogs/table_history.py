"""Popup: how a connectivity row's database tables have grown."""
from __future__ import annotations

import threading
from datetime import datetime

from energy_dashboard.common import *
from energy_dashboard.db.health_stats import fetch_table_growth

_LINE = (
    "#89b4fa", "#a6e3a1", "#f9e2af", "#cba6f7",
    "#fab387", "#94e2d5", "#f38ba8", "#74c7ec",
)


class TableHistoryDialog(QDialog):
    """Rows stored over time for the tables behind one connectivity row."""

    _ready = Signal(object)

    def __init__(self, parent, service: str, tables: list[str], backends: list[str], cap: dict):
        super().__init__(parent)
        self._service = service
        self._tables = list(tables)
        self._backends = list(backends)
        self._cap = cap
        self.setWindowTitle(f"Table history — {service}")
        self.setModal(True)
        self.resize(820, 520)
        self.setMinimumSize(640, 420)
        self.setStyleSheet(
            f"QDialog {{ background: {_DARK_SURFACE_BG}; }}"
            "QLabel { color: #cdd6f4; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        self.header = QLabel(self._intro())
        self.header.setWordWrap(True)
        self.header.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.header)
        self.fig = Figure(figsize=(8, 4.2), dpi=100)
        self.ax = self.fig.add_subplot(111)
        _style_ax_dark(self.ax, self.fig)
        self.fig.subplots_adjust(left=0.10, right=0.98, top=0.88, bottom=0.16)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumHeight(320)
        lay.addWidget(self.canvas, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        _apply_primary_button_style(close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self._ready.connect(self._show_result)
        if not self._tables:
            self._show_empty(
                "This row does not write a database table. "
                "The size on the status page is the live reading, not stored history."
            )
            return
        if not self._backends:
            self._show_empty("No database is enabled, so there is no table history to read.")
            return
        threading.Thread(target=self._load, daemon=True).start()

    def _intro(self) -> str:
        if not self._tables:
            return f"<b>{self._service}</b>"
        names = ", ".join(f"<code>{n}</code>" for n in self._tables)
        return (
            f"<b>{self._service}</b> · {names}<br>"
            "Reading how many rows were stored on each day…"
        )

    def _show_empty(self, message: str) -> None:
        self.header.setText(f"<b>{self._service}</b><br>{message}")
        self.ax.clear()
        _style_ax_dark(self.ax, self.fig)
        self.ax.text(
            0.5, 0.5, message,
            ha="center", va="center", transform=self.ax.transAxes,
            color="#a6adc8", fontsize=11, wrap=True,
        )
        self.ax.set_axis_off()
        self.canvas.draw_idle()

    def _load(self) -> None:
        best = None
        best_rows = -1
        for backend in self._backends:
            try:
                got = fetch_table_growth(backend, self._cap, self._tables)
            except Exception as exc:
                got = {"ok": False, "error": str(exc), "tables": {}}
            rows = sum(
                int((info or {}).get("row_count") or 0)
                for info in (got.get("tables") or {}).values()
            )
            got["backend"] = backend
            if rows > best_rows:
                best = got
                best_rows = rows
        self._ready.emit(best or {"ok": False, "error": "no database", "tables": {}})

    def _show_result(self, result: dict) -> None:
        tables = (result or {}).get("tables") or {}
        bits = []
        for name in self._tables:
            info = tables.get(name) or {}
            rows_n = info.get("row_count")
            sz = info.get("size_human")
            part = name
            if rows_n is not None:
                part += f" · {int(rows_n):,} rows"
            if sz:
                part += f" · {sz} now"
            bits.append(part)
        backend = (result or {}).get("backend") or ""
        head = f"<b>{self._service}</b>"
        if backend:
            head += f" · {backend}"
        if bits:
            head += "<br>" + "<br>".join(bits)
        head += (
            "<br><span style='color:#a6adc8'>The line is how many rows were in the "
            "table at the end of each day, counted from the time on each row. "
            "Disk size is the size right now.</span>"
        )
        self.header.setText(head)
        self._paint(tables)

    def _paint(self, tables: dict) -> None:
        import matplotlib.dates as mdates

        self.ax.clear()
        _style_ax_dark(self.ax, self.fig)
        drawn = 0
        for i, name in enumerate(self._tables):
            daily = (tables.get(name) or {}).get("daily") or []
            if not daily:
                continue
            xs = [datetime.strptime(p["date"], "%Y-%m-%d") for p in daily]
            ys = [p["cumulative"] for p in daily]
            self.ax.plot(
                xs, ys,
                color=_LINE[i % len(_LINE)],
                linewidth=1.6,
                label=name,
            )
            drawn += 1
        if not drawn:
            self.ax.text(
                0.5, 0.5, "No dated rows in these tables yet",
                ha="center", va="center", transform=self.ax.transAxes,
                color="#a6adc8", fontsize=11,
            )
            self.ax.set_axis_off()
        else:
            self.ax.set_title("Rows stored", fontsize=11, pad=4)
            self.ax.set_ylabel("Rows")
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
            self.ax.grid(axis="y", color="#313244", linewidth=0.4)
            self.ax.legend(
                loc="upper left", fontsize=8, framealpha=0.6,
                facecolor="#1e1e2e", edgecolor="#313244", labelcolor="#cdd6f4",
            )
        self.fig.subplots_adjust(left=0.10, right=0.98, top=0.88, bottom=0.16)
        self.canvas.draw_idle()
