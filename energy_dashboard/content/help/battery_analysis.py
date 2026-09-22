"""
Help text for BatteryAnalysisTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "BatteryAnalysisTab"

HELP_TEXT = """\
<h2>Battery Analysis</h2><p>
This page is in the <b>Physical Plant Tools</b> group. It reads SOC and battery power over the last N days from the Growatt cloud and visualises charge/discharge patterns alongside PV.</p>
<p>
<b>Refresh every:</b> next to Fetch Battery History, set how many minutes between automatic re-fetches (Off at 0). The choice is remembered. A fetch already in progress is not interrupted.</p>
<p>
The SOC chart has <b>Battery SOC (%)</b> on the left axis and, when <b>SOC change/hour</b> is ticked, a purple <b>SOC change (%/hour)</b> trace on the right axis — the instantaneous change in state of charge in percentage points per hour. The tick box state is remembered between sessions; hover always shows the rate next to SOC in the readout under the charts.</p>
<p>
<b>Optimization Insights</b> leads with a <b>Solar utilisation</b> table built only from measured power (PV / load / spare / charged kWh, base and peak load per day), then flags windows where genuine <b>spare</b> PV (generation minus house load) failed to charge the battery. Spare PV is the honest test: high PV with an equally high house load leaves nothing to charge with, and is a consumption problem rather than an inverter fault.</p>
<p>
<b>Battery capacity:</b> the kWh figure used for insights on this tab defaults to the pack size on <b>Growatt Live Status</b> (detected modules × 6.5&nbsp;kWh, or the inverter’s rated capacity). You can type a different number; <b>Save</b> keeps it. Until you Save, a later Live Status update can refresh the default.</p>
<p>
<b>AC charge stop %:</b> how full the inverter is allowed to take the pack on forced AC (grid) charge — Growatt’s <code>wchargeSOCLowLimit</code>. The spin is a normal number field (0–100&nbsp;%). <b>Save</b> stores capacity, low-SOC threshold, and this stop % on this computer. <b>Set on inverter</b> writes the stop % to the MIX via Growatt cloud (keeps existing charge periods) and reads it back to confirm. Charts always show measured SOC — never rescaled.</p>
<p>
<b>SOC fill:</b> under-curve colour is by measured SOC — red below 20&nbsp;%, yellow 20–50&nbsp;%, mid green 50–80&nbsp;%, stronger green at 80&nbsp;% and above.</p>
<p>
<b>Reconstructed SOC:</b> Growatt MIX-chart history is power only. When that is the only source, the SOC trace is integrated from charge/discharge and can pin at 0% — the title says <i>reconstructed</i>, and low-SOC events are suppressed because they would be artefacts. Prefer local GROTT logging (<code>growatt_readings</code>), which stores measured SOC. Grott only publishes when Shine sends a frame; an ~11&nbsp;min hole after the stick reconnects is a handshake gap (tray alarm), not overnight idle.</p>
<p>
<b>Grey \u201cNo data\u201d bands:</b> only where consecutive stored samples are far apart <i>and</i> the values actually change — a missing stretch, not the battery sitting still. Overnight SOC at the floor is drawn as a hold. Traces break across true holes instead of drawing a diagonal through them.</p>
<p>
<b>Live alarms</b> (Setup → Live alarms): logging database unreachable or no new Growatt/Tasmota rows while devices are live; Grott feed lost; inverter reported offline; Tasmota MQTT down or named plugs silent; SOC below threshold for the hold time; <b>spare PV not charging</b>; and <b>load consuming all PV</b>. Click the banner alarm text for detail.</p>
<p>
On the Power Flows chart, the previous two <b>London calendar days</b> and today are annotated with <b>Tot kWh consumed</b> (house load from <code>sysOut</code>), <b>Tot kWh imported</b>, and <b>Tot kWh generated</b> (PV). Today's values are marked <b>running</b> because they are incomplete.</p>
<p>
<b>Use it for:</b> validating the simulator's assumptions, spotting calendar-aging or capacity-fade trends.</p>
"""
