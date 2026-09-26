"""
Help text for PvStringChargeTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "PvStringChargeTab"

HELP_TEXT = """\
<h2>PV String Charge</h2><p>
This page is in the <b>Physical Plant</b> group. It shows an <b>estimate</b> of how much of the current battery charge is coming from each PV string. Growatt does not expose a measured “charge from string N” register — both strings feed a shared DC bus — so this tab apportions <code>chargePower</code> by each string’s share of total PV:</p>
<p style="font-family:monospace;color:#a6adc8;">
share_N ≈ chargePower × pPvN / (pPv1 + pPv2)
</p>
<p>
The coloured cards and the chart use the <b>same mapping</b>: blue is String 1, green is String 2. Each series is drawn from zero (not stacked on top of the other), so if String 1 is producing more, its line and fill sit <i>higher</i> than String 2. Fills are 50% opaque so overlaps stay readable; the 1 px line on each series is solid.</p>
<p>
If the battery is charging while PV is near zero (or grid import is high relative to PV), the tab labels the mode as <b>AC/grid charging</b> and does <i>not</i> split charge across strings. Discharge and idle are labelled separately.</p>
<p>
Each string card shows <b>now</b> (live PV power from that string, in kW) while the day is today, plus the energy since London midnight. On an earlier day the big figure on each string card is that day’s total kWh from the string, and the coloured line under it is that string’s percentage of the day’s PV. The line above that is still the estimated kWh into the battery. Battery charge shows measured kWh and what share of the day’s PV that charge represents. Total PV shows each string’s percentage. If stored samples only start later, the card says so instead of pretending the day is complete. Estimated charge into the battery is still labelled as an estimate — Growatt does not measure “charge from string N”.</p>
<p>
Click <b>String 1</b> or <b>String 2</b> to open a history table of measured generation from the stored 2-minute lots. Rows roll up as <b>Month → Day → Hour</b> (Europe/London): open a month for days, open a day for hours. Columns are String 1 kWh, String 2 kWh, total, and the relative balance (each string’s share of the two-string total). The column for the string you clicked is highlighted. This table is generation only — not the estimated charge into the battery.</p>
<p>
<b>Day</b> sits next to Reload charts. Click it to open a calendar and pick a London day. <b>Today</b> comes back to the current day. A future day is not offered. On today the big figures stay live kilowatts. On an earlier day they become that day’s kilowatt-hours for each string, with that string’s percentage of the day’s PV. The teal Now line is hidden then, and the totals are the stored samples only — they are not stretched up to the current clock.</p>
<p>
<b>Scan every (min)</b> sits next to those controls. It re-reads live string power on that interval so today’s charts fill in without clicking. 0 is Off. The value is remembered. Reload charts re-reads stored lots for the day on screen. Live samples are still saved while you look at an earlier day; they are not drawn onto that day.</p>
<p>
The chart is two stacked panes sharing that London day, midnight to midnight. The <b>top</b> pane is instantaneous power in <b>kW</b>: String 1, String 2, measured battery charge, and the solar forecast (brown, 30% fill) when a forecast for that day is stored. The <b>bottom</b> pane is energy in <b>kWh</b> accumulating from midnight: each string, both strings together (mauve), and the same solar forecast added up as a running total. Samples are stored as 2-minute lots in the <code>pv_string_charge</code> table. The energy-collector boot service writes those lots on each Growatt poll, so the day still fills in while this dashboard is closed. Lots from before the service was restarted are not invented. Dawn watts used to be stored as kW (stretching the old mixed axis to ~40 kW); string power is converted like total PV.</p>
"""
