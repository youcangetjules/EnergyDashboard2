"""
Help text for AnalyticsTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "AnalyticsTab"

HELP_TEXT = """\
<h2>Battery Simulation</h2><p>
The annual pounds are a <b>model</b>. They are not the Octopus bill, and they are not the inverter's measured import. After each run, <b>Simulation results — how the bill is calculated</b> shows the working with the numbers from that run.</p>
<p>
The history is house load and solar from the Growatt database when that has at least a day of half-hours. Each half-hour is the average kilowatts stored in it, times half an hour. That window's import cost minus export credit is divided by the whole days between the first and last slot, then multiplied by 365.</p>
<p>
<b>No Battery</b> lets solar cover the house, buys the rest, and sells the spare. <b>Current (2x)</b> replays the same history through a 13 kWh pack. The larger packs are the same replay. A bigger pack that never fills does not change the bill. Payback is the assumed cost of packs beyond that 13 kWh, divided by the fall in the modelled bill.</p>
<p>
Round-trip efficiency is applied on the way in and on the way out. The pack can use 95% of its nameplate and is not taken below 10%. It starts half full, and that starting energy is not added to the bill. Export is the flat pence rate, not Agile outgoing.</p>
"""
