"""
Energy Dashboard — `tabs/combined.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
class CombinedTab(QWidget):
    def __init__(self, growatt_tab, octopus_tab, status_callback):
        super().__init__()
        self.growatt_tab = growatt_tab
        self.octopus_tab = octopus_tab
        self.set_status = status_callback
        self.build_ui()

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)

        ctrl_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Combined View")
        refresh_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        refresh_btn.clicked.connect(self.refresh)
        ctrl_layout.addWidget(refresh_btn)
        hint = QLabel("(Load data in Growatt and Octopus tabs first)")
        hint.setStyleSheet("color: #6c7086; font-style: italic;")
        ctrl_layout.addWidget(hint)
        ctrl_layout.addStretch()
        main_layout.addLayout(ctrl_layout)

        splitter = QSplitter(Qt.Horizontal)

        _gb_style = (
            f"QGroupBox {{ background: {_DARK_SURFACE_BG}; border: 1px solid #313244; border-radius: 8px;"
            "  margin-top: 14px; padding: 10px 6px 6px 6px; color: #cdd6f4; font-weight: bold; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }"
        )

        left_widget = QGroupBox("Growatt Live Power Flow")
        left_widget.setStyleSheet(_gb_style)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 18, 4, 4)
        self.flow_fig = Figure(figsize=(6, 5), dpi=100)
        self.flow_ax = self.flow_fig.add_subplot(111)
        self.flow_canvas = FigureCanvas(self.flow_fig)
        left_layout.addWidget(self.flow_canvas)
        splitter.addWidget(left_widget)

        right_widget = QGroupBox("Octopus Daily Energy Trends")
        right_widget.setStyleSheet(_gb_style)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 18, 4, 4)
        self.trend_fig = Figure(figsize=(6, 5), dpi=100)
        self.trend_ax = self.trend_fig.add_subplot(111)
        self.trend_canvas = FigureCanvas(self.trend_fig)
        right_layout.addWidget(self.trend_canvas)
        splitter.addWidget(right_widget)

        main_layout.addWidget(splitter, 1)

    def _draw_power_flow(self, growatt_data):
        ax = self.flow_ax
        ax.clear()
        _style_ax_dark(ax, self.flow_fig)

        if growatt_data is None:
            ax.text(0.5, 0.5, 'No Growatt data\nConnect in Growatt tab',
                    ha='center', va='center', transform=ax.transAxes,
                    fontsize=13, color='#6c7086')
            ax.format_coord = lambda xv, yv: (
                "No Growatt snapshot — horizontal axis would be kW, vertical axis is flow row"
            )
            self.flow_fig.tight_layout()
            self.flow_canvas.draw()
            return

        def sf(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        gp = sf(growatt_data['grid_power'])
        if gp > 0.05:
            grid_cat = 'Grid (Export)'
        elif gp < -0.05:
            grid_cat = 'Grid (Import)'
        else:
            grid_cat = 'Grid'
        categories = ['PV', 'Battery', grid_cat, 'Load']
        values = [sf(growatt_data['pv_power']), sf(growatt_data['bat_power']),
                  gp, sf(growatt_data['load_power'])]
        colors = ['#fab387', '#a6e3a1', '#f38ba8', '#cba6f7']

        bars = ax.barh(categories, values, color=colors, height=0.55,
                       edgecolor='none', zorder=3)

        # Fixed asymmetric x-axis: −3 kW (max battery discharge) … +8 kW
        # (max load / grid draw). 0 stays prominent as the dividing reference
        # line so negative-vs-positive bars are visually anchored even though
        # the limits aren't symmetric. Static limits stop the chart "jumping"
        # between snapshots when one signal momentarily spikes.
        _PF_XLIM_LO, _PF_XLIM_HI = -3.0, 8.0
        ax.set_xlim(_PF_XLIM_LO, _PF_XLIM_HI)
        ax.axvline(0, color=_DARK_TEXT, linewidth=0.9, alpha=0.55, zorder=2)

        # Fixed label offset (in kW) — was previously tied to max_abs which
        # made labels jump. With an 11 kW visible span, 0.18 kW (~1.6 %)
        # places the text comfortably clear of each bar tip.
        _LABEL_OFFSET = 0.18

        for bar, val, cat in zip(bars, values, categories):
            if cat.startswith('Grid'):
                mag = abs(val)
                if val > 0.05:
                    value_txt = f'{mag:.2f} kW Export'
                elif val < -0.05:
                    value_txt = f'{mag:.2f} kW Import'
                else:
                    value_txt = f'{mag:.2f} kW'
            else:
                value_txt = f'{val:.2f} kW'
            # Positive (or zero) bar: label sits to the RIGHT of the tip.
            # Negative bar: label sits to the LEFT of the tip with ha='right'
            # so it never overlaps the bar itself or the y-axis tick labels.
            if val < 0:
                x_pos = bar.get_width() - _LABEL_OFFSET
                halign = 'right'
            else:
                x_pos = bar.get_width() + _LABEL_OFFSET
                halign = 'left'
            # Clamp inside the visible range so a value near the limit (e.g.
            # battery hitting −3 kW or load hitting +8 kW) still has a
            # readable label rather than disappearing past the spine.
            x_pos = min(max(x_pos, _PF_XLIM_LO + 0.05), _PF_XLIM_HI - 0.05)
            ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                    value_txt, ha=halign, va='center',
                    fontsize=11, fontweight='bold', color=_DARK_TEXT)

        soc = growatt_data.get('soc', '?')
        try:
            soc_val = float(soc)
            soc_color = '#a6e3a1' if soc_val > 50 else '#fab387' if soc_val > 20 else '#f38ba8'
        except (TypeError, ValueError):
            soc_val = None
            soc_color = '#6c7086'
        ax.set_title(f'Live Power Flow    SOC: {soc}%',
                     fontsize=12, fontweight='bold', color=soc_color, pad=10)
        ax.set_xlabel('kW', fontsize=10)
        ax.grid(axis='x', color=_DARK_GRID, linewidth=0.5, zorder=0)
        ax.tick_params(axis='y', labelsize=11, pad=4)
        now_str = datetime.now().strftime('%H:%M')
        ax.text(0.99, 0.01, now_str, transform=ax.transAxes, ha='right', va='bottom',
                fontsize=10, color='#6c7086', fontstyle='italic')
        ax.format_coord = lambda xv, yv: (
            f"Horizontal (x, kW): {xv:+.2f} — AC power (grid: + = export, − = import)  |  "
            f"Vertical (y): {yv:.2f} — bar row (PV, Battery, Grid, Load from bottom)"
        )
        self.flow_fig.tight_layout()
        self.flow_canvas.draw()

    def _draw_trends(self, octopus_data):
        ax = self.trend_ax
        ax.clear()
        _style_ax_dark(ax, self.trend_fig)

        if octopus_data is None:
            ax.text(0.5, 0.5, 'No Octopus data\nFetch in Octopus tab',
                    ha='center', va='center', transform=ax.transAxes,
                    fontsize=13, color='#6c7086')
            ax.format_coord = lambda xv, yv: "No Octopus daily totals — x would be date, y would be kWh"
            self.trend_fig.tight_layout()
            self.trend_canvas.draw()
            return

        dates = octopus_data.index
        imp = octopus_data['Import (kWh)']
        exp = octopus_data['Export (kWh)']
        net = octopus_data['Net (kWh)']

        ax.fill_between(dates, net, alpha=0.15, color=_UI_BLUE, zorder=1)
        ax.plot(dates, imp, color='#f38ba8', linewidth=1.8, label='Import', zorder=3)
        ax.plot(dates, exp, color='#a6e3a1', linewidth=1.8, label='Export', zorder=3)
        ax.plot(dates, net, color=_UI_BLUE, linewidth=1.2, linestyle='--',
                alpha=0.7, label='Net', zorder=2)
        ax.axhline(y=0, color=_DARK_GRID, linewidth=0.6)

        ax.set_ylabel('kWh', fontsize=10)
        ax.set_title('Daily Energy Trends', fontsize=12, fontweight='bold', pad=10)
        ax.legend(fontsize=9, loc='upper right', framealpha=0.6,
                  facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT)
        ax.grid(axis='y', color=_DARK_GRID, linewidth=0.4, zorder=0)
        now_str = datetime.now().strftime('%H:%M')
        ax.text(0.99, 0.01, now_str, transform=ax.transAxes, ha='right', va='bottom',
                fontsize=10, color='#6c7086', fontstyle='italic')
        self.trend_fig.autofmt_xdate()
        _draw_6h_vertical_grid(ax)
        _draw_day_date_labels(ax)
        import pytz
        _tz_tr = pytz.timezone('Europe/London')
        ax.format_coord = lambda xv, yv, tz=_tz_tr: _fmt_toolbar_time_y(
            xv, yv, tz, "kWh",
            "daily energy — compare y to import/export/net traces (pink/green/blue)",
        )
        self.trend_fig.tight_layout()
        self.trend_canvas.draw()

    def refresh(self):
        growatt_data = self.growatt_tab.get_live_data_summary()
        octopus_data = self.octopus_tab.get_daily_totals()
        has_growatt = growatt_data is not None
        has_octopus = octopus_data is not None
        if not has_growatt and not has_octopus:
            self.set_status("No data loaded. Connect Growatt and fetch Octopus data first.")
            return
        self._draw_power_flow(growatt_data)
        self._draw_trends(octopus_data)
        parts = []
        if has_growatt: parts.append("Growatt live")
        if has_octopus: parts.append(f"Octopus ({len(octopus_data)} days)")
        self.set_status(f"Combined view: {' + '.join(parts)}")


__all__ = [n for n in globals() if not n.startswith('__')]
