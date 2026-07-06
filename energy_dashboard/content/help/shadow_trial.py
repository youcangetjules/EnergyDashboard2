"""
Help text for ShadowTrialTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "ShadowTrialTab"

HELP_TEXT = """\
<h2>Shadow Trial</h2><p>
Benchmarks the inverter's <b>current live controller</b> (e.g. Growatt's Smart Scheduling AI, or plain self-consumption) against this dashboard's Optimiser — <b>without ever writing to the inverter</b>.</p>
<p>
Each night at ~23:35 (while the dashboard is open) the Optimiser plan for tomorrow is built from what is knowable at that moment — live SOC, current solar forecast, published Agile prices, learned usage profile — and <b>frozen</b> to the database. After each day completes, four contestants are scored on identical realised data:</p>
<ul>
<li>
<b>Actual</b> — what the inverter really did, priced from Octopus half-hourly meter data (billing-grade; appears a day or two late, rows show <i>pending</i> until then).</li>
<li>
<b>Shadow</b> — the frozen plan replayed against realised load/PV through the battery model, exactly as a MIX inverter would execute its schedule (AC-charge windows, forced-discharge windows, load-first otherwise).</li>
<li>
<b>Baseline</b> — simulated dumb load-first self-consumption (no scheduling at all).</li>
<li>
<b>Perfect</b> — the hindsight-optimal DP given the day's actual load, PV and prices: the theoretical ceiling.</li>
</ul>
<p>
<b>Capture</b> = (baseline − controller) ÷ (baseline − perfect): the share of that day's theoretically available savings the controller banked. Because it is normalised per-day, capture is comparable across days with different weather and price volatility. Judge on the <b>cumulative</b> figures over weeks — single days swing wildly, and day-boundary battery SOC differences only wash out over time.</p>
<p>
<b>Guard inverter writebacks</b> adds an extra warning to the Optimiser / Smart Advisor write buttons while the trial runs, so a habit click can't change the inverter's behaviour mid-trial and contaminate the comparison.</p>
<p>
Needs a database backend (Setup &amp; Info) and only freezes/scores while the dashboard is running. Missed nights simply leave gaps in the scoreboard.</p>
"""
