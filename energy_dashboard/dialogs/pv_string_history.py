"""Month → Day → Hour PV string generation and balance history."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from energy_dashboard.common import *
from energy_dashboard.db.pv_string_charge import query_pv_string_charge
from energy_dashboard.ui.buttons import _apply_primary_button_style, _prepare_dialog_buttons
from energy_dashboard.ui.columns import (
    qtree_attach_column_width_persistence,
    qtree_prepare_interactive_columns,
    qtree_restore_column_widths,
    qtree_set_column_width_key,
)

# Same 2-minute lot length as the store / chart.
_LOT_HOURS = 2.0 / 60.0
# How far back the tree will read (table is a ring buffer; this is a soft cap).
_LOOKBACK_DAYS = 550


def _london_tz():
    import pytz
    return pytz.timezone("Europe/London")


def _aware_utc(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _sanitize_kw(val) -> float:
    """Measured string PV may still be stored as watts on older lots."""
    try:
        n = float(val or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if abs(n) > 8.0:
        n = n / 1000.0
    return max(0.0, n)


def aggregate_string_history(rows) -> dict:
    """Roll 2-minute lots into London month → day → hour energy (kWh).

    Returns ``{ (year, month): { date: { hour: {pv1, pv2} } } }`` with hours
    as ints 0–23. Energy per lot is ``kW × (2/60)`` — the same rectangle width
    as a single stored sample on the live cards.
    """
    london = _london_tz()
    months: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(
        lambda: {"pv1": 0.0, "pv2": 0.0},
    )))
    for raw in rows or ():
        ts = _aware_utc(raw.get("t") if isinstance(raw, dict) else None)
        if ts is None:
            continue
        loc = ts.astimezone(london)
        pv1 = _sanitize_kw(raw.get("pv1"))
        pv2 = _sanitize_kw(raw.get("pv2"))
        if pv1 <= 0.0 and pv2 <= 0.0:
            continue
        mk = (loc.year, loc.month)
        day = loc.date()
        hour = int(loc.hour)
        bucket = months[mk][day][hour]
        bucket["pv1"] += pv1 * _LOT_HOURS
        bucket["pv2"] += pv2 * _LOT_HOURS
    return months


def _fmt_kwh(v: float) -> str:
    if v < 0.005:
        return "0.00"
    if v < 10:
        return f"{v:.2f}"
    return f"{v:.1f}"


def _balance_text(pv1: float, pv2: float) -> str:
    total = pv1 + pv2
    if total < 1e-9:
        return "—"
    p1 = 100.0 * pv1 / total
    p2 = 100.0 * pv2 / total
    return f"S1 {p1:.0f}% · S2 {p2:.0f}%"


def _sum_pair(parts) -> tuple[float, float]:
    s1 = s2 = 0.0
    for p in parts:
        s1 += float(p.get("pv1") or 0.0)
        s2 += float(p.get("pv2") or 0.0)
    return s1, s2


class PvStringHistoryDialog(QDialog):
    """Expandable Month → Day → Hour table of string generation and balance."""

    def __init__(self, parent, data_logger, *, focus_string: int = 1):
        super().__init__(parent)
        self._logger = data_logger
        self._focus = 1 if int(focus_string) != 2 else 2
        self.setWindowTitle("PV string history — generation and balance")
        self.setModal(True)
        self.resize(820, 560)
        self.setMinimumSize(640, 420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        which = f"String {self._focus}"
        self.header = QLabel(
            f"<p>Stored <b>2-minute lots</b> rolled up as "
            f"<b>Month → Day → Hour</b> (Europe/London). "
            f"Energy is measured string PV (kWh). Balance is each string’s "
            f"share of the two-string total — the same idea as the live cards. "
            f"You opened this from <b>{which}</b>; both strings are shown so "
            f"you can compare them.</p>"
            f"<p style='color:#a6adc8;'>Turn the arrows to open a month, then a "
            f"day for hours. Estimated charge into the battery is not in this "
            f"table — only generation.</p>"
        )
        self.header.setWordWrap(True)
        self.header.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self.header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels([
            "Period",
            "String 1 (kWh)",
            "String 2 (kWh)",
            "Total (kWh)",
            "Balance",
        ])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(18)
        qtree_prepare_interactive_columns(self.tree)
        qtree_set_column_width_key(self.tree, "pv_string_history")
        qtree_restore_column_widths(self.tree, "pv_string_history", resize_if_no_saved=True)
        qtree_attach_column_width_persistence(self.tree)
        outer.addWidget(self.tree, 1)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        btns = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Re-read stored lots and rebuild the tree.")
        refresh_btn.clicked.connect(self._reload)
        _apply_primary_button_style(refresh_btn)
        expand_btn = QPushButton("Expand months")
        expand_btn.setToolTip("Open every month row (days stay closed).")
        expand_btn.clicked.connect(self._expand_months)
        _apply_primary_button_style(expand_btn)
        collapse_btn = QPushButton("Collapse all")
        collapse_btn.clicked.connect(self.tree.collapseAll)
        _apply_primary_button_style(collapse_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        _apply_primary_button_style(close_btn)
        btns.addWidget(refresh_btn)
        btns.addWidget(expand_btn)
        btns.addWidget(collapse_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        outer.addLayout(btns)
        _prepare_dialog_buttons(self)

        self._reload()

    def _reload(self):
        self.tree.clear()
        if self._logger is None:
            self.status.setText("No database logger — nothing to show.")
            return
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=_LOOKBACK_DAYS)
        try:
            rows = query_pv_string_charge(
                self._logger, start_utc=start, end_utc=end,
            )
        except Exception as e:
            self.status.setText(f"Could not read pv_string_charge: {e}")
            return
        months = aggregate_string_history(rows)
        if not months:
            self.status.setText(
                "No stored string lots in the look-back window yet. "
                "Leave this tab scanning so 2-minute lots build up."
            )
            return

        london = _london_tz()
        now_loc = datetime.now(london)
        cur_month = (now_loc.year, now_loc.month)
        n_days = 0
        n_hours = 0
        for mk in sorted(months.keys(), reverse=True):
            day_map = months[mk]
            day_pairs = []
            for day in sorted(day_map.keys(), reverse=True):
                hours = day_map[day]
                h_pairs = [hours[h] for h in sorted(hours.keys())]
                d1, d2 = _sum_pair(h_pairs)
                day_pairs.append((day, hours, d1, d2))
            m1 = sum(d[2] for d in day_pairs)
            m2 = sum(d[3] for d in day_pairs)
            month_item = self._row_item(
                datetime(mk[0], mk[1], 1).strftime("%B %Y"),
                m1, m2, bold=True,
            )
            self.tree.addTopLevelItem(month_item)
            for day, hours, d1, d2 in day_pairs:
                n_days += 1
                day_item = self._row_item(
                    day.strftime("%a %d %b %Y"), d1, d2,
                )
                month_item.addChild(day_item)
                for hour in sorted(hours.keys()):
                    n_hours += 1
                    h = hours[hour]
                    hour_item = self._row_item(
                        f"{hour:02d}:00–{hour:02d}:59",
                        float(h["pv1"]), float(h["pv2"]),
                    )
                    day_item.addChild(hour_item)
            if mk == cur_month:
                month_item.setExpanded(True)

        self.status.setText(
            f"{len(months)} month(s), {n_days} day(s), {n_hours} hour(s) "
            f"from {len(rows)} stored lot(s)."
        )
        if self.tree.topLevelItemCount() and not any(
            self.tree.topLevelItem(i).isExpanded()
            for i in range(self.tree.topLevelItemCount())
        ):
            self.tree.topLevelItem(0).setExpanded(True)

    def _row_item(self, label: str, pv1: float, pv2: float, *, bold: bool = False):
        total = pv1 + pv2
        item = QTreeWidgetItem([
            label,
            _fmt_kwh(pv1),
            _fmt_kwh(pv2),
            _fmt_kwh(total),
            _balance_text(pv1, pv2),
        ])
        for col in range(1, 5):
            item.setTextAlignment(col, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if bold:
            font = item.font(0)
            font.setBold(True)
            for col in range(5):
                item.setFont(col, font)
        # Soft highlight on the string the user clicked from.
        focus_col = 1 if self._focus == 1 else 2
        accent = QColor("#89b4fa" if self._focus == 1 else "#a6e3a1")
        item.setForeground(focus_col, QBrush(accent))
        return item

    def _expand_months(self):
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(True)
