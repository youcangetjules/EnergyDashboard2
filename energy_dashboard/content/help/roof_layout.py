"""
Help text for RoofLayoutTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "RoofLayoutTab"

HELP_TEXT = """\
<h2>Roof layout</h2><p>
This page is in <b>Physical Plant Tools</b>. It builds a multi-face roof model for a better solar forecast. Each <b>face</b> has its own
tilt, azimuth, panel type and count (kWp), plus which inverter <b>string</b> (MPPT /
series-wired run) those panels feed. When you <b>Apply to Forecasts</b>, the Forecasts
tab fetches one PV curve per enabled face and sums them — more accurate than a single
average tilt/azimuth.</p>
<p><b>Satellite / Google Earth workflow</b></p>
<ol>
<li>The right-hand panel is a live <b>satellite map</b> centered on the Forecasts
lat/lon. Use the top <b>Imagery</b> menu:
<ul>
<li><b>Google Satellite / Hybrid</b> — the current photo only. Google’s tile server no longer returns older satellite versions.</li>
<li><b>Historic satellite</b> — dated aerial archive (Esri Wayback, 2014→now). Pick <b>Year</b> and <b>Release</b>, or ◀/▶ through the timeline. These are not old Google photos.</li>
<li><b>Esri Live</b> — current mosaic; the chip at the bottom shows the scene capture date</li>
<li><b>Sentinel-2 cloudless</b> (2018 / 2021 / 2024) — annual mosaics (~10&nbsp;m; timeline context, not panel edges)</li>
</ul>
<b>Use clearest image</b> scores those sources (plus a sample of Wayback dates) at the current roof and switches to the sharpest tiles — the one where panel edges look least blurred. The choice is remembered next time you open Roof Layout.</li>
<li>Select a roof face → <b>Draw outline</b> (optional) for the array footprint.</li>
<li><b>Orientation:</b> <b>Select top edge</b> then <b>Select bottom edge</b> —
click two ends of each edge on the map. Azimuth is measured from the <b>top edge
pointing toward the bottom edge</b>. <b>Set tilt</b> applies the tilt spinbox to
that face. Use <b>Add roof face</b> for each array with a different facing.</li>
<li>Optional: <b>Open Google Earth</b>, <b>Load GE image…</b>, or <b>Import KML…</b>.</li>
</ol>
<p><b>String</b> is the DC string / MPPT number on the inverter (1, 2, …). Several faces
can share one string if they are series-wired together; different facings on separate
MPPTs get different numbers.</p>
<p><b>Azimuth</b> is degrees <b>0…359</b> only: <b>0° = south</b>, 90° = west,
180° = north, 270° = east. <b>Flip azimuth</b> adds 180° (e.g. 55.2° → 235.2°).
Panel types come from <b>Panel database</b> in this same group. kWp is
that module’s watts × the count on the face.</p>
<p><b>Use single-plane</b> turns multi-face fetch off again; Forecasts then uses its own
Tilt / Azimuth / kWp fields (your saved faces are kept).</p>
"""
