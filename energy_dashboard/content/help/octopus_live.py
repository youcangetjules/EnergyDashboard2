"""
Help text for OctopusLiveTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "OctopusLiveTab"

HELP_TEXT = """\
<h2>Octopus Live</h2><p>
Polls the Octopus consumption API on a tight cadence to give a near-real-time view of import / export and net at 1-min / 5-min / 30-min granularity. Useful when validating tariff assumptions or watching a particular event (e.g. EV charge session).</p>
<p>
The line next to <b>Fetch Live Data</b> starts with <b>Connectivity</b>. Green <b>OK</b> means the live GraphQL stream answered. Amber <b>REST only</b> means that stream did not, so the half-hour meter (often about a day behind) is filling in. Amber <b>stale</b> means auto-refresh is on but Octopus has not answered for a few minutes. Red <b>failed</b> means the last request did not succeed. The same word sits on the bottom strip as <b>Octopus</b>, next to the database. “Latest … ago” is how old the newest meter slot is — that is separate from whether Octopus answered.</p>
<p>
<b>Hours</b> and <b>View: Power / Cost</b> sit on the API-key row, with a vertical rule between them. <b>Save</b> is immediately to the right of View, and <b>Test</b> is to the right of Save. Test checks that Octopus accepts the API key and account; it does not reload the charts. <b>Power</b> is watts and kWh. <b>Cost</b> is that same energy times the Agile spot price (the half-hour unit rate, including VAT — the import and export tariffs from Forecasts / Setup). Positive money is what you pay to import; negative money is export credit. The standing charge is not included, so this is not the final bill.</p>
<p>
Octopus’s half-hour meter — the readings a bill is built from — usually arrives later and does not match the live stream exactly. For each completed earlier day where both exist, the app divides what Octopus’s meter would have cost by what the live stream would have cost, and takes the middle of those ratios. That scale is applied only to <b>today</b>, and the chart labels today as an estimate. A settled day on the chart is the Octopus meter itself, not the scaled live line. If a ratio would stretch or shrink the estimate by more than half, it is held at that limit and the summary says so.</p>
<p>
On the top chart, each <b>London calendar day</b> in view is annotated with <b>Total imported</b> (kWh, top-right of that day) and <b>Total exported</b> (kWh, bottom-left); partial days count only intervals visible in the window. In Cost view those notes are pounds instead, marked settled or est.</p>
<p>
In <b>Power</b> view the <b>bottom chart</b> is a <b>cumulative</b> view that <b>resets at each
London calendar midnight</b>: running <b>import</b> (from live demand / meter
intervals), running <b>PV generation</b> (from Growatt readings in the database),
and <b>total consumption</b> as the meter balance <code>import + PV − export</code>
— an analysis line from those series, not a separate BMS register. Across a
multi-day window the lines drop back to zero at 00:00 each day. End-of-day
<b>Imp / PV / Cons</b> totals are labelled under each completed day's last point;
today's values are labelled at the latest sample as a running tally. If the
PV line is missing, the overlay could not read <code>growatt_readings</code>
— connecting to PostgreSQL is not enough; the Setup login must be allowed
to <b>SELECT</b> that table (the MQTT broker account usually is not).
In <b>Cost</b> view the bottom chart is cumulative pounds instead — import cost, export credit, and net — and it still resets at midnight. Today’s line is the estimate.</p>
"""
