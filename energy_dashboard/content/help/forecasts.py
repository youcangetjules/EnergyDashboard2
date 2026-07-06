"""
Help text for ForecastsTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "ForecastsTab"

HELP_TEXT = """\
<h2>Forecasts</h2><p>
Pulls Octopus Agile import &amp; export half-hourly prices and a solar generation forecast: <b>Forecast.Solar</b> first; if that is unreachable or empty, an <b>Open-Meteo</b> hourly tilted-irradiance backup scaled to your kWp. The API curve starts today — past calendar days have no watts. The previous London day is filled from measured Growatt PV; a dashed line can still show yesterday's DB-saved <i>planned</i> forecast for accuracy checks.</p>
<p>
<b>Location handling</b></p>
<ul>
<li>
Lat / Lon are <code>DECIMAL(10,5)</code> — values snap to 5 dp on commit and persist immediately to QSettings.</li>
<li>
<b>Tilt</b>, <b>Azimuth</b> and <b>kWp</b> persist to the same keys when you leave each field, or use <b>Save parameters</b> for an explicit write and status confirmation.</li>
<li>
<b>Show on map</b> opens an OpenStreetMap picker with optional what3words lookup.</li>
<li>
The Locale label is reverse-geocoded via OpenStreetMap Nominatim (fine zoom so village/town names appear when available) and cached.</li>
</ul>
"""
