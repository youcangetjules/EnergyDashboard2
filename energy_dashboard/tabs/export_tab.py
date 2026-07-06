"""
Energy Dashboard — `tabs/export_tab.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
class ExportTab(QWidget):
    """Export a 30-min sliding-window snapshot to .xlsx.

    The window is centred on "now" with configurable half-width (default
    1.5 days each side), so the workbook contains both an actual history
    column for the past half and a usage-prediction column for the future
    half.  Columns produced (one per 30-min slot, indexed in London time):

      - timestamp_local   : 30-min slot start, Europe/London
      - timestamp_utc     : same slot start, UTC (for downstream tooling)
      - is_future         : True / False — convenience flag for filtering
      - spot_price_import : p/kWh inc. VAT — Octopus Agile import
      - spot_price_export : p/kWh — Octopus Agile outgoing / export
      - usage_kwh_actual  : measured import (kWh) per slot, blank for future
      - usage_kwh_predict : forecast import (kWh) per slot, blank for past
                            unless the user opts to backfill predictions
      - soc_pct           : measured battery SOC %, blank for future

    The prediction is a simple "same time-of-day × same day-of-week"
    median over the last N weeks of `octopus_readings`, with a fallback
    to the same time-of-day across all available history when not enough
    matching weeks exist.  This is deliberately explainable rather than
    clever — the more history the database accumulates, the better it
    gets, which is why continuous logging matters.
    """

    EXPORT_COLS = (
        'timestamp_local',
        'timestamp_utc',
        'is_future',
        'spot_price_import',
        'spot_price_export',
        'usage_kwh_actual',
        'usage_kwh_predict',
        'soc_pct',
    )

    def __init__(self, app_params, data_logger, status_callback):
        super().__init__()
        self.app_params = app_params
        self.data_logger = data_logger
        self.set_status = status_callback
        self._inv = Invoker(self)
        self.on_data_updated = None
        self._last_df = None
        self._last_path = None
        self.build_ui()

    # ── UI ───────────────────────────────────────────────────────────

    def build_ui(self):
        self.setStyleSheet(f"background-color: {_DARK_BG};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)

        ctrl.addWidget(QLabel("Window half-width (days):"))
        self.sp_half = QDoubleSpinBox()
        self.sp_half.setDecimals(2)
        self.sp_half.setRange(0.25, 14.0)
        self.sp_half.setSingleStep(0.5)
        self.sp_half.setValue(1.5)
        self.sp_half.setToolTip(
            "Half-width of the sliding window in days. The default 1.5 "
            "yields a 3-day window (1.5 days of history before 'now', "
            "1.5 days of forecast after)."
        )
        ctrl.addWidget(self.sp_half)

        ctrl.addWidget(QLabel("Prediction lookback (weeks):"))
        self.sp_weeks = QSpinBox()
        self.sp_weeks.setRange(1, 26)
        self.sp_weeks.setValue(4)
        self.sp_weeks.setToolTip(
            "How many past weeks of half-hourly Octopus consumption to "
            "average when building the usage prediction. Median across "
            "matching (weekday, half-hour) slots is used."
        )
        ctrl.addWidget(self.sp_weeks)

        self.cb_backfill = QCheckBox("Also predict for past slots")
        self.cb_backfill.setToolTip(
            "When enabled, fill the usage_kwh_predict column even for "
            "past slots — useful for offline accuracy comparison."
        )
        ctrl.addWidget(self.cb_backfill)

        ctrl.addStretch(1)

        self.btn_preview = QPushButton("Preview")
        self.btn_preview.setToolTip("Build the dataset in memory and show a summary below — does not write a file.")
        self.btn_preview.clicked.connect(self._on_preview_clicked)
        ctrl.addWidget(self.btn_preview)

        self.btn_export = QPushButton("Export .xlsx…")
        self.btn_export.clicked.connect(self._on_export_clicked)
        ctrl.addWidget(self.btn_export)

        layout.addLayout(ctrl)

        # Status / summary
        self.status_label = QLabel("Ready — click Preview to build, then Export to save .xlsx.")
        self.status_label.setStyleSheet("color:#bac2de; padding:2px 0;")
        layout.addWidget(self.status_label)

        # Preview text area
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        _apply_dark_log_view(
            self.preview,
            object_name='exportPreviewView',
            extra_qss=(
                "font-family: 'Cascadia Mono', 'JetBrains Mono', Consolas, monospace; "
                "font-size: 11px; border-radius: 4px; padding: 6px;"
            ),
        )
        self.preview.setPlainText(
            "No preview yet.\n\n"
            "The Export tab assembles a 30-minute time-series workbook centred on the current\n"
            "moment, pulling:\n\n"
            "  - Octopus Agile import / export prices (from the on-disk snapshots, falling\n"
            "    back to a live API call so the future half includes any prices already\n"
            "    published by Octopus).\n"
            "  - Half-hourly Octopus consumption (the historic-usage column).\n"
            "  - Growatt battery SOC %, resampled to 30-min means.\n"
            "  - A weekday-aware 'same time of day' median forecast for the future half.\n\n"
            "Click Preview to assemble the dataset and Export to save it as .xlsx."
        )
        layout.addWidget(self.preview, 1)

    # ── Build dataset ────────────────────────────────────────────────

    def _slot_index_london(self, half_days: float, now_utc: pd.Timestamp):
        """Return a half-hourly DatetimeIndex (London tz) covering
        ``now ± half_days``, snapped to the nearest 30-min boundary."""
        half = pd.Timedelta(days=float(half_days))
        # Snap "now" down to the start of its 30-min slot so the index
        # aligns with Octopus / Agile half-hour boundaries.
        anchor = (now_utc.floor('30min')
                          .tz_convert('Europe/London'))
        start = anchor - half
        end = anchor + half - pd.Timedelta(minutes=30)
        idx = pd.date_range(start=start, end=end, freq='30min',
                            tz='Europe/London')
        return idx

    def _build_predictions(self, idx_london, octopus_df, lookback_weeks: int,
                            include_past: bool, now_utc: pd.Timestamp):
        """Return a Series aligned to ``idx_london`` carrying predicted
        import kWh per 30-min slot, using a (weekday × half-hour) median
        over the last ``lookback_weeks`` of measured Octopus data.

        Falls back to the all-history (half-hour-only) median when a
        given (weekday, half-hour) bucket has no observations.  Past
        slots remain NaN unless ``include_past`` is True (used for
        offline accuracy checks).
        """
        if octopus_df is None:
            return pd.Series(np.nan, index=idx_london, dtype=float)
        if isinstance(octopus_df, pl.DataFrame):
            if octopus_df.is_empty():
                return pd.Series(np.nan, index=idx_london, dtype=float)
            df = octopus_df.to_pandas()
        elif octopus_df.empty:
            return pd.Series(np.nan, index=idx_london, dtype=float)
        else:
            df = octopus_df.copy()
        df = df.set_index(pd.to_datetime(df['interval_start'], utc=True)) \
               .tz_convert('Europe/London')
        df = df[['import_kwh']].dropna()

        cutoff = (now_utc.tz_convert('Europe/London')
                          - pd.Timedelta(weeks=int(lookback_weeks)))
        recent = df[df.index >= cutoff]

        # Median per (weekday 0-6, minute-of-day 0-1410) bucket.
        def _bucket_key(ix):
            return list(zip(ix.weekday, ix.hour * 60 + ix.minute))

        if not recent.empty:
            keys = _bucket_key(recent.index)
            recent = recent.assign(_wd=[k[0] for k in keys],
                                   _mod=[k[1] for k in keys])
            wd_mod_med = recent.groupby(['_wd', '_mod'])['import_kwh'].median()
        else:
            wd_mod_med = pd.Series(dtype=float)

        # Time-of-day-only fallback uses the full (not just recent) history.
        keys_all = _bucket_key(df.index)
        df_all = df.assign(_mod=[k[1] for k in keys_all])
        tod_med = df_all.groupby('_mod')['import_kwh'].median()

        out = []
        for ts in idx_london:
            if (not include_past) and (ts.tz_convert('UTC') <= now_utc):
                out.append(np.nan)
                continue
            mod = ts.hour * 60 + ts.minute
            wd = ts.weekday()
            v = wd_mod_med.get((wd, mod), np.nan)
            if pd.isna(v):
                v = tod_med.get(mod, np.nan)
            out.append(float(v) if not pd.isna(v) else np.nan)
        return pd.Series(out, index=idx_london, dtype=float)

    def _live_agile_dfs(self):
        """Try a live Agile API call so the future half of the window
        sees the freshest prices Octopus has published.  Failures are
        non-fatal — the on-disk snapshot fallback still works."""
        p = self.app_params
        out = {'import': None, 'export': None}
        try:
            df = fetch_agile_prices(p.agile_product, p.agile_tariff)
            out['import'] = df
        except Exception as e:
            _log.warn(f"ExportTab: live Agile import fetch failed: {e}")
        try:
            df = fetch_agile_standard_unit_rates(p.agile_product, p.agile_export_tariff)
            out['export'] = df
        except Exception as e:
            _log.warn(f"ExportTab: live Agile export fetch failed: {e}")
        return out

    def _coerce_agile_to_series(self, df, idx_london):
        """Convert any Agile DataFrame variant (live API or DB snapshot)
        into a pence-per-kWh Series aligned to ``idx_london``.
        """
        if df is None:
            return pd.Series(np.nan, index=idx_london, dtype=float)
        if isinstance(df, pl.DataFrame):
            if df.is_empty():
                return pd.Series(np.nan, index=idx_london, dtype=float)
            d = df.to_pandas()
        elif len(df) == 0:
            return pd.Series(np.nan, index=idx_london, dtype=float)
        else:
            d = df.copy()
        # Live API gives 'valid_from' / 'value_inc_vat'; DB snapshot gives
        # 'valid_from' / 'price_pence'. Normalise both.
        if 'value_inc_vat' in d.columns:
            d = d.rename(columns={'value_inc_vat': 'price_pence'})
        if 'valid_from' not in d.columns or 'price_pence' not in d.columns:
            return pd.Series(np.nan, index=idx_london, dtype=float)
        d['valid_from'] = pd.to_datetime(d['valid_from'], utc=True)
        d = d.dropna(subset=['valid_from', 'price_pence'])
        d = d.sort_values('valid_from').drop_duplicates('valid_from', keep='last')
        s = pd.Series(d['price_pence'].values,
                      index=d['valid_from'].dt.tz_convert('Europe/London'))
        # Reindex onto the half-hour grid; Agile is already 30-min so
        # this is essentially a labelled lookup.
        return s.reindex(idx_london)

    def _build_dataframe(self):
        """Assemble the export DataFrame.  Returns (df, summary_lines)."""
        half = float(self.sp_half.value())
        weeks = int(self.sp_weeks.value())
        include_past_pred = self.cb_backfill.isChecked()

        now_utc = pd.Timestamp.now(tz='UTC')
        idx = self._slot_index_london(half, now_utc)
        idx_utc = idx.tz_convert('UTC')

        # Pull DB sources (best effort — empty frames are ok).
        try:
            oct_db = self.data_logger.query_octopus_consumption(
                idx_utc[0] - pd.Timedelta(weeks=weeks + 1),  # extra history for prediction
                idx_utc[-1] + pd.Timedelta(minutes=30),
            )
        except Exception as e:
            _log.warn(f"ExportTab: octopus_readings query failed: {e}")
            oct_db = pl.DataFrame(schema={
                'interval_start': pl.Datetime('us', 'UTC'),
                'import_kwh': pl.Float64,
                'export_kwh': pl.Float64,
            })
        try:
            soc_db = self.data_logger.query_growatt_soc(
                idx_utc[0], idx_utc[-1] + pd.Timedelta(minutes=30),
            )
        except Exception as e:
            _log.warn(f"ExportTab: growatt SOC query failed: {e}")
            soc_db = pl.DataFrame(schema={
                'timestamp': pl.Datetime('us', 'UTC'),
                'soc_pct': pl.Float64,
            })

        p = self.app_params
        agile_in_db = self.data_logger.query_agile_prices(
            idx_utc[0], idx_utc[-1] + pd.Timedelta(minutes=30),
            p.agile_tariff, direction='import',
        )
        agile_ex_db = self.data_logger.query_agile_prices(
            idx_utc[0], idx_utc[-1] + pd.Timedelta(minutes=30),
            p.agile_export_tariff, direction='export',
        )
        live = self._live_agile_dfs()

        # Build aligned columns.
        s_imp_db = self._coerce_agile_to_series(agile_in_db, idx)
        s_imp_live = self._coerce_agile_to_series(live['import'], idx)
        # Prefer live prices where available (covers the future half), fall
        # back to DB snapshots (covers the past).
        s_imp = s_imp_live.combine_first(s_imp_db)

        s_exp_db = self._coerce_agile_to_series(agile_ex_db, idx)
        s_exp_live = self._coerce_agile_to_series(live['export'], idx)
        s_exp = s_exp_live.combine_first(s_exp_db)

        # Historic usage from octopus_readings (interval_start is the
        # 30-min slot start UTC; rename to align with the index).
        if not oct_db.is_empty():
            oct_pd = oct_db.to_pandas()
            oct_pd['interval_start'] = pd.to_datetime(oct_pd['interval_start'], utc=True) \
                                         .dt.tz_convert('Europe/London')
            usage_actual = (oct_pd.set_index('interval_start')['import_kwh']
                                  .reindex(idx))
        else:
            usage_actual = pd.Series(np.nan, index=idx, dtype=float)

        # SOC: 5-min snapshots → 30-min mean.  We resample on the full
        # series first then reindex onto the export grid.
        if not soc_db.is_empty():
            soc_pd = soc_db.to_pandas()
            soc_pd['timestamp'] = pd.to_datetime(soc_pd['timestamp'], utc=True) \
                                    .dt.tz_convert('Europe/London')
            soc_series = (soc_pd.set_index('timestamp')['soc_pct']
                                .resample('30min').mean()
                                .reindex(idx))
        else:
            soc_series = pd.Series(np.nan, index=idx, dtype=float)

        # Predictions — reuse the wider history we already pulled into
        # oct_db (it intentionally extends `weeks + 1` further back than
        # the export window for exactly this purpose).
        usage_predict = self._build_predictions(
            idx, oct_db, weeks, include_past_pred, now_utc,
        )

        # For past slots we don't generally fill the predict column unless
        # the user opted in via the checkbox.
        if not include_past_pred:
            past_mask = idx.tz_convert('UTC') <= now_utc
            usage_predict.loc[past_mask] = np.nan

        # Likewise mask actual usage / SOC in the future half (they'll
        # naturally be NaN, but be explicit).
        future_mask = idx.tz_convert('UTC') > now_utc
        usage_actual.loc[future_mask] = np.nan
        soc_series.loc[future_mask] = np.nan

        out = pd.DataFrame({
            'timestamp_local':   idx,
            'timestamp_utc':     idx.tz_convert('UTC'),
            'is_future':         future_mask,
            'spot_price_import': s_imp.values,
            'spot_price_export': s_exp.values,
            'usage_kwh_actual':  usage_actual.values,
            'usage_kwh_predict': usage_predict.values,
            'soc_pct':           soc_series.values,
        }, columns=list(self.EXPORT_COLS))

        # Build a short human-readable summary.
        n_past = int((~future_mask).sum())
        n_future = int(future_mask.sum())

        def _coverage(s):
            try:
                return f"{int(s.notna().sum()):>3} / {len(s):>3}"
            except Exception:
                return f"  ? / {len(s):>3}"

        summary = [
            f"Window: {idx[0]:%Y-%m-%d %H:%M %Z}  →  {idx[-1]:%Y-%m-%d %H:%M %Z}",
            f"Slots:  {len(idx)}  (past: {n_past}, future: {n_future})  ·  "
            f"now ≈ {now_utc.tz_convert('Europe/London'):%Y-%m-%d %H:%M %Z}",
            "",
            f"  spot_price_import : {_coverage(out['spot_price_import'])}  populated",
            f"  spot_price_export : {_coverage(out['spot_price_export'])}  populated",
            f"  usage_kwh_actual  : {_coverage(out['usage_kwh_actual'])}  populated  (past only)",
            f"  usage_kwh_predict : {_coverage(out['usage_kwh_predict'])}  populated  "
            f"({'incl. past backfill' if include_past_pred else 'future only'})",
            f"  soc_pct           : {_coverage(out['soc_pct'])}  populated  (past only)",
        ]
        if oct_db.is_empty():
            summary.append("\n⚠ No Octopus consumption rows found in DB — enable Octopus logging "
                            "for the prediction model to learn.")
        if not self.data_logger.sqlite_enabled:
            summary.append("\n⚠ SQLite logging is disabled; columns sourced from the DB will be empty.")
        return out, summary

    # ── Button handlers ──────────────────────────────────────────────

    def _on_preview_clicked(self):
        self.btn_preview.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.set_status("Export: building preview…")
        threading.Thread(target=self._preview_thread, daemon=True).start()

    def _preview_thread(self):
        try:
            df, summary = self._build_dataframe()
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            _log.warn(f"ExportTab preview failed: {e}\n{tb}")
            self._inv.invoke(lambda msg=str(e): self._show_error(msg))
            return
        self._inv.invoke(lambda d=df, s=summary: self._apply_preview(d, s))

    def _apply_preview(self, df, summary):
        self._last_df = df
        head = df.head(8).to_string(index=False)
        tail = df.tail(8).to_string(index=False)
        text = (
            "\n".join(summary)
            + "\n\n────  HEAD  ────────────────────────────────────────────────\n"
            + head
            + "\n\n────  TAIL  ────────────────────────────────────────────────\n"
            + tail
        )
        self.preview.setPlainText(text)
        self.status_label.setText(f"Preview built — {len(df)} rows × {len(df.columns)} cols. Ready to export.")
        self.set_status("Export: preview ready.")
        self.btn_preview.setEnabled(True)
        self.btn_export.setEnabled(True)
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    def _on_export_clicked(self):
        if self._last_df is None:
            # Build first, then save in one shot.
            self.btn_preview.setEnabled(False)
            self.btn_export.setEnabled(False)
            self.set_status("Export: building dataset…")
            threading.Thread(target=self._export_then_save_thread, daemon=True).start()
            return
        self._prompt_and_save(self._last_df)

    def _export_then_save_thread(self):
        try:
            df, summary = self._build_dataframe()
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            _log.warn(f"ExportTab build failed: {e}\n{tb}")
            self._inv.invoke(lambda msg=str(e): self._show_error(msg))
            return
        self._inv.invoke(lambda d=df, s=summary: self._after_build_save(d, s))

    def _after_build_save(self, df, summary):
        self._apply_preview(df, summary)
        self._prompt_and_save(df)

    def _prompt_and_save(self, df):
        default_name = (
            f"powermodel_export_{pd.Timestamp.now(tz='Europe/London'):%Y%m%d_%H%M}.xlsx"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export 30-min sliding window to .xlsx",
            default_name, "Excel workbook (*.xlsx)",
        )
        if not path:
            self.set_status("Export: save cancelled.")
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        try:
            self._write_xlsx(df, path)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            _log.warn(f"ExportTab save failed: {e}\n{tb}")
            QMessageBox.critical(self, "Export failed",
                                 f"Couldn't write the workbook:\n\n{e}")
            self.set_status(f"Export: failed — {e}")
            return
        self._last_path = path
        self.status_label.setText(
            f"Exported {len(df)} rows to:  {path}"
        )
        self.set_status(f"Export: saved {len(df)} rows to {path}")
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    def _show_error(self, msg):
        self.btn_preview.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.status_label.setText(f"Error: {msg}")
        self.set_status(f"Export: failed — {msg}")
        QMessageBox.warning(self, "Export error", str(msg))

    # ── Workbook writer ──────────────────────────────────────────────

    def _write_xlsx(self, df, path):
        """Write the export DataFrame to .xlsx via openpyxl, with a frozen
        header row, an auto-filter, basic number formats, and a small
        'README' sheet describing each column."""
        # Cast tz-aware columns to naive local strings — Excel can't store
        # tz info and openpyxl will otherwise warn / strip it silently.
        out = df.copy()
        out['timestamp_local'] = (out['timestamp_local']
                                    .dt.tz_convert('Europe/London')
                                    .dt.strftime('%Y-%m-%d %H:%M:%S'))
        out['timestamp_utc'] = (out['timestamp_utc']
                                  .dt.tz_convert('UTC')
                                  .dt.strftime('%Y-%m-%d %H:%M:%S'))
        # Excel-friendly bool column.
        out['is_future'] = out['is_future'].astype(bool)

        with pd.ExcelWriter(path, engine='openpyxl') as xl:
            out.to_excel(xl, sheet_name='30min_window', index=False)
            self._write_readme_sheet(xl)
            ws = xl.sheets['30min_window']
            self._format_main_sheet(ws, len(out))

    def _format_main_sheet(self, ws, n_rows):
        try:
            from openpyxl.styles import Font, PatternFill, Alignment
        except Exception:
            return
        header_font = Font(bold=True, color='FFFFFFFF')
        header_fill = PatternFill('solid', fgColor='FF1E1E2E')
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        col_widths = {
            'A': 22, 'B': 22, 'C': 11,
            'D': 18, 'E': 18, 'F': 18, 'G': 18, 'H': 12,
        }
        for col, w in col_widths.items():
            ws.column_dimensions[col].width = w
        # Number formats for the numeric columns.
        n_fmt_price = '0.00'
        n_fmt_kwh = '0.000'
        n_fmt_pct = '0.0'
        for r in range(2, n_rows + 2):
            ws.cell(row=r, column=4).number_format = n_fmt_price  # spot import
            ws.cell(row=r, column=5).number_format = n_fmt_price  # spot export
            ws.cell(row=r, column=6).number_format = n_fmt_kwh    # actual usage
            ws.cell(row=r, column=7).number_format = n_fmt_kwh    # predicted
            ws.cell(row=r, column=8).number_format = n_fmt_pct    # SOC

    def _write_readme_sheet(self, xl):
        try:
            wb = xl.book
            ws = wb.create_sheet('README')
        except Exception:
            return
        rows = [
            ('Column', 'Units', 'Description'),
            ('timestamp_local', 'Europe/London', '30-min slot start in local civil time (BST/GMT auto).'),
            ('timestamp_utc',   'UTC',           'Same slot start in UTC — useful for downstream tooling.'),
            ('is_future',       'bool',          'TRUE if the slot is after "now" at export time, else FALSE.'),
            ('spot_price_import', 'p/kWh',       'Octopus Agile import unit rate inc. VAT. Live API preferred, DB snapshot fallback.'),
            ('spot_price_export', 'p/kWh',       'Octopus Agile outgoing / export unit rate. Same source preference.'),
            ('usage_kwh_actual',  'kWh',         'Measured grid import per 30-min slot from octopus_readings. Empty for future slots.'),
            ('usage_kwh_predict', 'kWh',         'Predicted import from the (weekday × half-hour) median over the lookback window. Empty for past slots unless backfill enabled.'),
            ('soc_pct',           '%',           'Battery state-of-charge from growatt_readings, resampled to 30-min mean. Empty for future slots.'),
            ('', '', ''),
            ('Method note', '', 'Predictions improve as more half-hourly data accumulates in octopus_readings. Continuous logging matters: the model needs at least a few weeks of history to give confident weekday-aware estimates.'),
        ]
        for r, row in enumerate(rows, start=1):
            for c, val in enumerate(row, start=1):
                ws.cell(row=r, column=c, value=val)
        try:
            from openpyxl.styles import Font
            for cell in ws[1]:
                cell.font = Font(bold=True)
        except Exception:
            pass
        ws.column_dimensions['A'].width = 22
        ws.column_dimensions['B'].width = 16
        ws.column_dimensions['C'].width = 90


__all__ = [n for n in globals() if not n.startswith('__')]
