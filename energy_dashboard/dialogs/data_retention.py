"""
Connectivity architecture pill — per-table ring-buffer activate + limits.
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.db.retention import (
    RetentionPolicy,
    RetentionTarget,
    load_policy,
    prune_all_for_logger,
    prune_console_log,
    save_policy,
    targets_for_box,
)
from energy_dashboard.ui.styles import (
    _retention_activate_btn_qss,
    _retention_row_action_btn_qss,
)


class _RetentionRow(QGroupBox):
    """One table/store: activate toggle, ring-buffer spins, Save and Prune."""

    saved = Signal(str, str)  # key, message
    pruned = Signal(str, str)  # key, message

    def __init__(
        self,
        target: RetentionTarget,
        stats: dict | None,
        *,
        data_logger=None,
        parent=None,
    ):
        super().__init__(parent)
        self.target = target
        self._stats = stats or {}
        self._logger = data_logger
        self.setTitle(target.label)
        self.setStyleSheet(
            "QGroupBox {"
            "  border: 1px solid #45475a;"
            "  border-radius: 6px;"
            "  margin-top: 12px;"
            "  padding: 8px 10px 10px 10px;"
            "  color: #cdd6f4;"
            "}"
            "QGroupBox::title {"
            "  subcontrol-origin: margin;"
            "  left: 8px;"
            "  padding: 0 6px;"
            "  color: #a6adc8;"
            "}"
        )

        root = QVBoxLayout(self)
        root.setSpacing(6)

        meta_parts = [f"<code>{target.key}</code>"]
        if self._stats.get("row_count") is not None:
            meta_parts.append(f"{self._stats['row_count']:,} rows")
        if self._stats.get("last_activity"):
            meta_parts.append(f"last {self._stats['last_activity']}")
        if self._stats.get("size_human"):
            meta_parts.append(self._stats["size_human"])
        meta = QLabel(" · ".join(meta_parts))
        meta.setStyleSheet("color: #6c7086; font-size: 10px;")
        meta.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(meta)

        if target.note:
            note = QLabel(target.note)
            note.setWordWrap(True)
            note.setStyleSheet("color: #6c7086; font-size: 10px;")
            root.addWidget(note)

        pol = load_policy(target.key)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.btn_activate = QPushButton("Activate")
        self.btn_activate.setCheckable(True)
        self.btn_activate.setChecked(pol.enabled)
        self.btn_activate.setToolTip(
            "Turn ring-buffer trimming on or off for this table, then click Save."
        )
        self.btn_activate.toggled.connect(self._on_activate_toggled)
        self._style_activate_btn()
        top.addWidget(self.btn_activate)
        top.addStretch()
        root.addLayout(top)

        limits = QGridLayout()
        limits.setHorizontalSpacing(10)
        limits.setVerticalSpacing(4)

        self.sp_rows = QSpinBox()
        self.sp_rows.setRange(0, 50_000_000)
        self.sp_rows.setSingleStep(10_000)
        self.sp_rows.setSpecialValueText("unlimited")
        self.sp_rows.setValue(pol.max_rows)
        self.sp_rows.setToolTip("0 = unlimited. Oldest rows deleted first.")
        apply_spin_field_motif(self.sp_rows, width=140)
        self.sp_rows.setProperty("_pm_spin_motif_w", 140)

        self.sp_days = QSpinBox()
        self.sp_days.setRange(0, 3650)
        self.sp_days.setSpecialValueText("unlimited")
        self.sp_days.setValue(pol.max_age_days)
        self.sp_days.setToolTip("0 = unlimited. Deletes rows older than this many days.")
        apply_spin_field_motif(self.sp_days, width=140)
        self.sp_days.setProperty("_pm_spin_motif_w", 140)

        self.sp_mb = QDoubleSpinBox()
        self.sp_mb.setRange(0.0, 50_000.0)
        self.sp_mb.setDecimals(1)
        self.sp_mb.setSpecialValueText("unlimited")
        self.sp_mb.setValue(pol.max_size_mb)
        self.sp_mb.setToolTip(
            "0 = unlimited. PostgreSQL: table size via pg_total_relation_size; "
            "SQLite: approximate by trimming oldest rows."
        )
        apply_spin_field_motif(self.sp_mb, width=140)
        self.sp_mb.setProperty("_pm_spin_motif_w", 140)

        for row, (lbl, widget) in enumerate(
            (
                ("Max rows:", self.sp_rows),
                ("Max age (days):", self.sp_days),
                ("Max size (MB):", self.sp_mb),
            )
        ):
            lab = QLabel(lbl)
            lab.setStyleSheet("color: #a6adc8; font-size: 11px;")
            limits.addWidget(lab, row, 0)
            limits.addWidget(widget, row, 1)
        root.addLayout(limits)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_save = QPushButton("Save")
        self.btn_save.setToolTip("Store limits for this table")
        self.btn_save.setStyleSheet(_retention_row_action_btn_qss())
        self.btn_save.clicked.connect(self._on_save)
        self.btn_prune = QPushButton("Prune now")
        self.btn_prune.setToolTip("Save, then delete oldest rows until within limits")
        self.btn_prune.setStyleSheet(_retention_row_action_btn_qss())
        self.btn_prune.clicked.connect(self._on_prune)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_prune)
        actions.addStretch()
        root.addLayout(actions)

    def _style_activate_btn(self) -> None:
        on = self.btn_activate.isChecked()
        self.btn_activate.setText("Active" if on else "Activate")
        self.btn_activate.setStyleSheet(_retention_activate_btn_qss(active=on))

    def _on_activate_toggled(self, _checked: bool) -> None:
        self._style_activate_btn()

    def policy(self) -> RetentionPolicy:
        return RetentionPolicy(
            enabled=self.btn_activate.isChecked(),
            max_rows=self.sp_rows.value(),
            max_age_days=self.sp_days.value(),
            max_size_mb=self.sp_mb.value(),
        )

    def _persist(self) -> None:
        save_policy(self.target.key, self.policy())

    def _on_save(self) -> None:
        self._persist()
        summary = self.policy().summary()
        self.saved.emit(self.target.key, f"{self.target.label}: saved ({summary}).")

    def _on_prune(self) -> None:
        self._persist()
        pol = self.policy()
        if not pol.enabled:
            self.pruned.emit(
                self.target.key,
                f"{self.target.label}: enable the ring buffer before pruning.",
            )
            return
        if self._logger is None:
            self.pruned.emit(self.target.key, f"{self.target.label}: no data logger configured.")
            return
        key = self.target.key
        if key == "console_log":
            n = prune_console_log(pol)
            if n:
                self.pruned.emit(self.target.key, f"{self.target.label}: removed {n:,} log lines.")
            else:
                self.pruned.emit(
                    self.target.key,
                    f"{self.target.label}: nothing removed (already within limits).",
                )
            return
        results = prune_all_for_logger(self._logger, table_keys=[key])
        if not results:
            self.pruned.emit(
                self.target.key,
                f"{self.target.label}: nothing removed (already within limits).",
            )
            return
        parts = [f"{k}: {v:,}" for k, v in results.items()]
        self.pruned.emit(
            self.target.key,
            f"{self.target.label}: pruned — " + ", ".join(parts),
        )


class ConnectivityRetentionDialog(QDialog):
    """Architecture pill popup — one panel per table with activate + ring-buffer controls."""

    def __init__(
        self,
        box_key: str,
        summary_body: str,
        *,
        table_stats: dict | None = None,
        data_logger=None,
        dash=None,
        parent=None,
    ):
        super().__init__(parent)
        title = {
            "database": "Databases",
            "export": "Exported data",
            "storage": "Databases & Exports",
        }.get(box_key, box_key)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self._box_key = box_key
        self._logger = data_logger
        self._rows: list[_RetentionRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        intro = QLabel(
            "<span style='color:#6c7086;'>Each table has its own <b>Activate</b> button and "
            "ring-buffer limits. Trimming removes <b>oldest</b> rows first. "
            "Use <b>0</b> for unlimited on a cap. Limits combine: a row is removed if it "
            "violates <i>any</i> enabled cap.</span>"
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(intro)

        login = None
        if dash is not None:
            from energy_dashboard.dialogs.component_login import build_component_login

            login = build_component_login(box_key, dash)
            if login is not None:
                self.setMinimumWidth(720)

        summary = QTextEdit()
        summary.setReadOnly(True)
        summary.setFont(QFont("Helvetica", 10))
        summary.setFrameShape(QFrame.Shape.NoFrame)
        summary.setPlainText(summary_body)
        summary.setMaximumHeight(280)
        root.addWidget(summary)

        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setStyleSheet("background: #45475a; max-height: 1px;")
        root.addWidget(rule)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setSpacing(8)
        if login is not None:
            inner_lay.addWidget(login)
        stats = table_stats or {}
        for target in targets_for_box(box_key):
            row = _RetentionRow(
                target,
                stats.get(target.key),
                data_logger=data_logger,
                parent=inner,
            )
            row.saved.connect(self._on_row_saved)
            row.pruned.connect(self._on_row_pruned)
            self._rows.append(row)
            inner_lay.addWidget(row)
        inner_lay.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #6c7086; font-size: 11px;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        buttons = QDialogButtonBox()
        save_all = buttons.addButton(
            "Save all", QDialogButtonBox.ButtonRole.ActionRole
        )
        prune_all = buttons.addButton(
            "Prune all", QDialogButtonBox.ButtonRole.ActionRole
        )
        close_btn = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        save_all.setStyleSheet(_retention_row_action_btn_qss())
        prune_all.setStyleSheet(_retention_row_action_btn_qss())
        save_all.clicked.connect(self._on_save_all)
        prune_all.clicked.connect(self._on_prune_all)
        close_btn.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        screen = QApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() if screen is not None else 800
        self.resize(
            760 if login is not None else 600,
            min(780, int(avail_h * 0.88)),
        )

    def _set_status(self, text: str, *, ok: bool = True) -> None:
        self._status.setText(text)
        color = "#a6e3a1" if ok else "#f38ba8"
        self._status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _on_row_saved(self, _key: str, message: str) -> None:
        self._set_status(message, ok=True)

    def _on_row_pruned(self, _key: str, message: str) -> None:
        ok = "enable the ring buffer" not in message and "no data logger" not in message
        self._set_status(message, ok=ok)

    def _save_all(self) -> None:
        for row in self._rows:
            row._persist()

    def _on_save_all(self) -> None:
        self._save_all()
        self._set_status("All retention settings saved.", ok=True)

    def _on_prune_all(self) -> None:
        self._save_all()
        if self._logger is None:
            self._set_status("No data logger configured.", ok=False)
            return
        keys = [r.target.key for r in self._rows]
        if "console_log" in keys:
            n = prune_console_log(load_policy("console_log"))
            keys = [k for k in keys if k != "console_log"]
            if n:
                self._set_status(f"Console log: removed {n:,} lines; pruning tables…", ok=True)
        results = prune_all_for_logger(self._logger, table_keys=keys)
        if not results:
            self._set_status(
                "Prune finished — nothing removed (limits off or already within caps).",
                ok=True,
            )
            return
        parts = [f"{k}: {v:,} removed" for k, v in results.items()]
        self._set_status("Prune finished — " + "; ".join(parts), ok=True)
