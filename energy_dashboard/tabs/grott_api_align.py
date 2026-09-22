"""
Energy Dashboard — Grott vs Growatt API alignment (Calculators group).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from energy_dashboard.common import *
from energy_dashboard.fetch.grott_api_align import compare_grott_to_api

_DEFAULT_INTERVAL_MIN = 120
_MIN_INTERVAL_MIN = 15
_MAX_INTERVAL_MIN = 24 * 60
# Reuse a Live Status cloud read up to this old instead of polling the API
# ourselves. The pair is internally consistent (Grott snapshot captured at
# the same moment), so age only means "slightly older comparison".
_REUSE_MAX_AGE_S = 600.0
_HISTORY_MAX = 48
_COL_KEY = "grott_api_align"
_COL_DEFAULTS = (160, 100, 100, 120, 100, 220)
_QS_ORG, _QS_APP = "PowerModel", "EnergyDashboard2"
_QS_AUTO = "grott_align/auto_enabled"
_QS_AUTO_LEGACY = "grott_align/auto_30min"
_QS_INTERVAL = "grott_align/interval_min"

_RESULT_LABEL = {
    "aligned": "Aligned",
    "mismatch": "Mismatch",
    "grott_only": "Grott only",
    "api_only": "API only",
    "both_missing": "Neither",
}
_RESULT_COLOUR = {
    "aligned": "#a6e3a1",
    "mismatch": "#f38ba8",
    "grott_only": "#fab387",
    "api_only": "#89b4fa",
    "both_missing": "#6c7086",
}


def _fmt_val(val, unit: str) -> str:
    if val is None:
        return "—"
    try:
        num = float(val)
    except (TypeError, ValueError):
        return "—"
    if unit == "%":
        return f"{num:.1f}"
    if unit in ("V", "Hz"):
        return f"{num:.2f}"
    return f"{num:.3f}"


def _fmt_delta(delta, unit: str) -> str:
    if delta is None:
        return "—"
    sign = "+" if float(delta) > 0 else ""
    return f"{sign}{_fmt_val(delta, unit)}"


def _api_not_contactable_message(exc: BaseException) -> str | None:
    """Return a clear status when the cloud endpoint cannot be reached."""
    try:
        import requests
    except ImportError:
        requests = None  # type: ignore

    text = str(exc or "").strip()
    low = text.lower()
    if requests is not None and isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
        ),
    ):
        detail = text.split("\n", 1)[0].strip() or type(exc).__name__
        if len(detail) > 120:
            detail = detail[:117] + "..."
        return f"Growatt cloud API is not contactable ({detail})"
    needles = (
        "connection refused",
        "connection reset",
        "name or service not known",
        "nodename nor servname",
        "temporary failure in name resolution",
        "network is unreachable",
        "failed to establish a new connection",
        "max retries exceeded",
        "timed out",
        "timeout",
        "unreachable",
        "ssl:",
        "certificate",
    )
    if any(n in low for n in needles):
        detail = text.split("\n", 1)[0].strip() or "network/TLS error"
        if len(detail) > 120:
            detail = detail[:117] + "..."
        return f"Growatt cloud API is not contactable ({detail})"
    return None


def _api_align_fetch_error(exc: BaseException) -> str:
    contact = _api_not_contactable_message(exc)
    if contact:
        return contact
    try:
        return _growatt_v1_error_message(exc)
    except Exception:
        return str(exc) or type(exc).__name__


class GrottApiAlignTab(QWidget):
    """Compare Grott MQTT live registers with a Growatt cloud live read."""

    def __init__(self, growatt_tab, status_callback):
        super().__init__()
        self.growatt_tab = growatt_tab
        self.set_status = status_callback
        self._inv = Invoker(self)
        self.on_data_updated = None
        self._busy = False
        self._history = []
        self._next_auto_at = None
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self._start_compare(oneshot=False))
        self._load_auto_settings()
        self._tick_schedule()
        self._clock = QTimer(self)
        self._clock.setInterval(15_000)
        self._clock.timeout.connect(self._tick_schedule)
        self._clock.start()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.lbl_intro = QLabel("")
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        root.addWidget(self.lbl_intro)

        ctrl = QHBoxLayout()
        self.btn_now = QPushButton("Compare now")
        self.btn_now.setToolTip(
            "One-shot compare. Reuses the Live Status page's most recent cloud "
            "read when one is fresh (no extra API call); otherwise makes one "
            "poll through the shared Open API budget. Waits out any active "
            "rate-limit pause instead of risking a longer one."
        )
        self.btn_now.clicked.connect(lambda: self._start_compare(oneshot=True))
        _apply_primary_button_style(self.btn_now)
        ctrl.addWidget(self.btn_now)
        self.chk_auto = QCheckBox("Automatic every")
        self.chk_auto.setToolTip(
            "While the dashboard is open, run the comparison on this interval. "
            "Reuses the Live Status page's latest cloud read when fresh (no "
            "extra API poll); skipped while the Open API is in a rate-limit "
            "pause. Connection failures are reported as not contactable."
        )
        self.chk_auto.toggled.connect(self._on_auto_toggled)
        ctrl.addWidget(self.chk_auto)
        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(_MIN_INTERVAL_MIN, _MAX_INTERVAL_MIN)
        self.sp_interval.setValue(_DEFAULT_INTERVAL_MIN)
        self.sp_interval.setSuffix(" min")
        self.sp_interval.setFixedWidth(110)
        self.sp_interval.setToolTip(
            f"Automatic compare interval ({_MIN_INTERVAL_MIN}–{_MAX_INTERVAL_MIN} min). "
            f"Default {_DEFAULT_INTERVAL_MIN} min."
        )
        self.sp_interval.valueChanged.connect(self._on_interval_changed)
        ctrl.addWidget(self.sp_interval)
        ctrl.addStretch(1)
        self.lbl_schedule = QLabel("")
        self.lbl_schedule.setStyleSheet("color: #a6adc8; font-size: 11px;")
        ctrl.addWidget(self.lbl_schedule)
        root.addLayout(ctrl)
        self._refresh_intro()

        self.lbl_summary = QLabel(
            f"No comparison yet. Click Compare now, or wait for the "
            f"{_DEFAULT_INTERVAL_MIN}-minute automatic timer."
        )
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(
            "color: #cdd6f4; padding: 8px; border: 1px solid #45475a; "
            "border-radius: 4px; background: transparent;"
        )
        root.addWidget(self.lbl_summary)

        hist_row = QHBoxLayout()
        hist_row.addWidget(QLabel("History:"))
        self.cmb_history = QComboBox()
        self.cmb_history.setMinimumWidth(280)
        self.cmb_history.currentIndexChanged.connect(self._on_history_picked)
        hist_row.addWidget(self.cmb_history, 1)
        root.addLayout(hist_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            ["Field", "Grott", "Cloud API", "Δ (Grott−API)", "Result", "Notes"]
        )
        self.tree.setColumnCount(6)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        self._apply_tree_columns()
        root.addWidget(self.tree, 1)

    def _refresh_intro(self) -> None:
        mins = int(self.sp_interval.value()) if hasattr(self, "sp_interval") else _DEFAULT_INTERVAL_MIN
        self.lbl_intro.setText(
            "Compare the live <b>Grott MQTT</b> snapshot with a Growatt "
            "<b>cloud API</b> live read. Reuses the <b>Live Status</b> page's "
            "most recent cloud read when it is fresh — no extra API call and "
            "no impact on that page's polling; otherwise one poll goes through "
            "the shared Open API budget. Automatic runs every "
            f"<b>{mins}</b> minutes when enabled; <b>Compare now</b> is a "
            "one-shot. Aligned = within tolerance. If the cloud cannot be "
            "reached, the status says the API is not contactable. "
            "Grott-estimated load/grid is noted, not treated as a decode "
            "failure."
        )

    def _interval_minutes(self) -> int:
        try:
            return max(
                _MIN_INTERVAL_MIN,
                min(_MAX_INTERVAL_MIN, int(self.sp_interval.value())),
            )
        except Exception:
            return _DEFAULT_INTERVAL_MIN

    def _load_auto_settings(self) -> None:
        qs = QSettings(_QS_ORG, _QS_APP)
        if qs.contains(_QS_INTERVAL):
            try:
                mins = int(qs.value(_QS_INTERVAL, _DEFAULT_INTERVAL_MIN))
            except (TypeError, ValueError):
                mins = _DEFAULT_INTERVAL_MIN
        else:
            mins = _DEFAULT_INTERVAL_MIN
        mins = max(_MIN_INTERVAL_MIN, min(_MAX_INTERVAL_MIN, mins))
        self.sp_interval.blockSignals(True)
        self.sp_interval.setValue(mins)
        self.sp_interval.blockSignals(False)
        if qs.contains(_QS_AUTO):
            auto = qs.value(_QS_AUTO, True, type=bool)
        else:
            auto = qs.value(_QS_AUTO_LEGACY, True, type=bool)
        self.chk_auto.blockSignals(True)
        self.chk_auto.setChecked(bool(auto))
        self.chk_auto.blockSignals(False)
        self._apply_auto_timer(restart=True)
        self._refresh_intro()

    def _persist_auto_settings(self) -> None:
        qs = QSettings(_QS_ORG, _QS_APP)
        qs.setValue(_QS_AUTO, bool(self.chk_auto.isChecked()))
        qs.setValue(_QS_INTERVAL, int(self._interval_minutes()))

    def _apply_auto_timer(self, *, restart: bool) -> None:
        mins = self._interval_minutes()
        self._timer.setInterval(mins * 60 * 1000)
        if self.chk_auto.isChecked():
            if restart or not self._timer.isActive():
                self._timer.start()
            self._next_auto_at = datetime.now() + timedelta(minutes=mins)
        else:
            self._timer.stop()
            self._next_auto_at = None

    def _apply_tree_columns(self) -> None:
        """Restore saved widths (or defaults); re-apply after each table fill."""
        tree = self.tree
        qtree_set_column_width_key(tree, _COL_KEY)
        qtree_prepare_interactive_columns(tree)
        if not qtree_restore_column_widths(tree, _COL_KEY, resize_if_no_saved=False):
            for i, w in enumerate(_COL_DEFAULTS):
                tree.setColumnWidth(i, w)
        if not getattr(tree, "_qcol_persist_attached", False):
            qtree_attach_column_width_persistence(tree)

    def hideEvent(self, event):
        super().hideEvent(event)
        try:
            qtree_save_column_widths(self.tree, _COL_KEY)
        except Exception:
            pass

    def _on_auto_toggled(self, checked: bool):
        self._persist_auto_settings()
        self._apply_auto_timer(restart=True)
        self._tick_schedule()

    def _on_interval_changed(self, _value: int):
        self._persist_auto_settings()
        self._refresh_intro()
        self._apply_auto_timer(restart=True)
        self._tick_schedule()

    def _tick_schedule(self):
        if self._busy:
            self.lbl_schedule.setText("Comparing…")
            return
        if self.chk_auto.isChecked() and self._next_auto_at is not None:
            self.lbl_schedule.setText(
                f"Next automatic: {self._next_auto_at.strftime('%H:%M')} "
                f"(every {self._interval_minutes()} min)"
            )
        else:
            self.lbl_schedule.setText("Automatic compares off")

    def compare_now(self):
        """Refresh Page / Refresh All hook."""
        self._start_compare(oneshot=True)

    def _start_compare(self, *, oneshot: bool):
        if self._busy:
            if oneshot:
                self.set_status("Grott/API align: a compare is already running.")
            return
        # Uses ONLY the public sibling contract on GrowattTab (get_grott_snapshot,
        # get_cloud_session, get_recent_cloud_pair, open_api_gate,
        # fetch_cloud_live_for_sibling) — never its private attributes, so this
        # page cannot silently starve or pause the Live Status page.
        gt = self.growatt_tab

        # Prefer the Live page's most recent cloud read: it is paired with a
        # Grott snapshot captured at the same moment, costs no Open API call,
        # and cannot delay the Live page's own polling.
        pair = gt.get_recent_cloud_pair(_REUSE_MAX_AGE_S)
        if pair is not None:
            self._launch_compare(
                pair.get("grott_snap"), False, "", oneshot, pair=pair,
            )
            return

        snap, stale = gt.get_grott_snapshot(allow_stale=True)
        api, device_sn, plant_id = gt.get_cloud_session()
        gate = gt.open_api_gate()

        skip_api = ""
        if gate["rate_limited"]:
            # Never call the API during a pause (a failed call would re-arm
            # the 30-minute pause and take Live Status offline for longer).
            skip_api = (
                f"Open API rate-limit pause ({int(gate['pause_s'])}s left) "
                "— showing Grott only"
            )
        elif gate["wait_s"] > 0:
            skip_api = (
                f"Open API 5-min spacing ({int(gate['wait_s'])}s left) "
                "— showing Grott only"
            )
        if not skip_api and (api is None or not device_sn):
            skip_api = (
                "Growatt cloud API is not contactable — not connected "
                "(use Connect on Growatt Live Status first)"
            )
        self._launch_compare(
            snap, stale, skip_api, oneshot,
            api=api, device_sn=device_sn, plant_id=plant_id,
        )

    def _launch_compare(
        self, snap, stale, skip_api, oneshot,
        *, api=None, device_sn="", plant_id=None, pair=None,
    ):
        self._busy = True
        self.btn_now.setEnabled(False)
        self._tick_schedule()
        kind = "one-shot" if oneshot else f"{self._interval_minutes()}-minute"
        if pair is not None:
            self.set_status(
                f"Grott/API align: running {kind} compare "
                f"(reusing Live Status cloud read, {pair['age_s']:.0f}s old)…"
            )
        else:
            self.set_status(f"Grott/API align: running {kind} compare…")
        threading.Thread(
            target=self._compare_worker,
            args=(snap, stale, api, device_sn, plant_id, skip_api, oneshot),
            kwargs={"pair": pair},
            daemon=True,
        ).start()

    def _compare_worker(
        self, snap, stale, api, device_sn, plant_id, skip_api, oneshot,
        pair=None,
    ):
        api_status = api_info = api_totals = None
        api_err = skip_api
        reused_age = None
        if pair is not None:
            api_status = pair.get("status")
            api_info = pair.get("info")
            api_totals = pair.get("totals")
            api_err = ""
            reused_age = float(pair.get("age_s") or 0.0)
        elif not api_err:
            try:
                api_status, api_info, api_totals = (
                    self.growatt_tab.fetch_cloud_live_for_sibling(
                        api, device_sn, plant_id,
                    )
                )
            except Exception as exc:
                api_err = _api_align_fetch_error(exc)
                api_status = api_info = api_totals = None
        # Grott age relative to when the cloud side was read, so reused pairs
        # are judged by their own moment of capture, not by "now".
        grott_age = None
        if isinstance(snap, dict):
            ref = _time_mod.time() - (reused_age or 0.0)
            try:
                grott_age = max(0.0, ref - float(snap.get("received_at")))
            except (TypeError, ValueError):
                grott_age = None
        compared = compare_grott_to_api(snap, api_status, api_info, api_totals)
        grott_ok = grott_age is not None and grott_age <= 180
        payload = {
            "when": datetime.now(),
            "oneshot": bool(oneshot),
            "stale_grott": bool(stale),
            "grott_age_s": grott_age,
            "grott_fresh": grott_ok,
            "api_error": api_err or "",
            "api_ok": api_status is not None and not api_err,
            "reused_age_s": reused_age,
            **compared,
        }
        self._inv.invoke(lambda p=payload: self._finish_compare(p))

    def _finish_compare(self, payload: dict):
        self._busy = False
        self.btn_now.setEnabled(True)
        if self.chk_auto.isChecked():
            self._next_auto_at = datetime.now() + timedelta(
                minutes=self._interval_minutes(),
            )
        self._history.insert(0, payload)
        del self._history[_HISTORY_MAX:]
        self._fill_history_combo(select=0)
        self._render_run(payload)
        self._tick_schedule()
        n_mis = int(payload.get("mismatch") or 0)
        n_ok = int(payload.get("aligned") or 0)
        kind = "one-shot" if payload.get("oneshot") else "scheduled"
        api_err = payload.get("api_error") or ""
        extra = f" — {api_err}" if api_err else ""
        self.set_status(
            f"Grott/API align ({kind}): {n_ok} aligned, {n_mis} mismatch{extra}"
        )
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    def _fill_history_combo(self, select: int = 0):
        self.cmb_history.blockSignals(True)
        self.cmb_history.clear()
        for i, run in enumerate(self._history):
            when = run.get("when")
            ts = when.strftime("%H:%M:%S") if hasattr(when, "strftime") else "?"
            tag = "now" if run.get("oneshot") else "auto"
            mis = int(run.get("mismatch") or 0)
            ok = int(run.get("aligned") or 0)
            err = (run.get("api_error") or "").strip()
            if not err:
                api = "API reused" if run.get("reused_age_s") is not None else "API ok"
            elif "not contactable" in err.lower():
                api = "API not contactable"
            elif "rate-limit" in err.lower() or "pause" in err.lower():
                api = "API pause"
            else:
                api = "API skip"
            self.cmb_history.addItem(
                f"{ts}  {tag}  {ok} aligned / {mis} mismatch  ({api})",
                i,
            )
        self.cmb_history.blockSignals(False)
        if self.cmb_history.count():
            self.cmb_history.setCurrentIndex(
                max(0, min(select, self.cmb_history.count() - 1))
            )

    def _on_history_picked(self, idx: int):
        if idx < 0 or idx >= len(self._history):
            return
        self._render_run(self._history[idx])

    def _render_run(self, payload: dict):
        when = payload.get("when")
        ts = when.strftime("%Y-%m-%d %H:%M:%S") if hasattr(when, "strftime") else "—"
        age = payload.get("grott_age_s")
        if age is None:
            grott_bit = "no Grott snapshot"
        else:
            grott_bit = f"Grott {age:.0f}s old"
            if payload.get("stale_grott") or not payload.get("grott_fresh"):
                grott_bit += " (stale)"
        api_bit = "cloud live read OK"
        reused = payload.get("reused_age_s")
        if reused is not None:
            api_bit = (
                f"cloud read reused from Live Status ({reused:.0f}s old, "
                "no extra API call)"
            )
        if payload.get("api_error"):
            api_bit = payload["api_error"]
        n_ok = payload.get("aligned") or 0
        n_mis = payload.get("mismatch") or 0
        n_g = payload.get("grott_only") or 0
        n_a = payload.get("api_only") or 0
        self.lbl_summary.setText(
            f"<b>{ts}</b> · {grott_bit} · {api_bit}<br>"
            f"Aligned <b>{n_ok}</b> · mismatch <b>{n_mis}</b> · "
            f"Grott-only {n_g} · API-only {n_a}"
        )
        self.tree.clear()
        for row in payload.get("rows") or []:
            unit = row.get("unit") or ""
            result = row.get("result") or ""
            item = QTreeWidgetItem([
                row.get("label") or row.get("field") or "",
                _fmt_val(row.get("grott"), unit),
                _fmt_val(row.get("api"), unit),
                _fmt_delta(row.get("delta"), unit),
                _RESULT_LABEL.get(result, result),
                row.get("notes") or "",
            ])
            col = QColor(_RESULT_COLOUR.get(result, "#cdd6f4"))
            item.setForeground(4, QBrush(col))
            if result == "mismatch":
                item.setForeground(3, QBrush(col))
            self.tree.addTopLevelItem(item)
        self._apply_tree_columns()


__all__ = ["GrottApiAlignTab"]
