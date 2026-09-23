"""
Help text for AgileYearTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "AgileYearTab"

HELP_TEXT = """\
<h2>Agile Year</h2><p>
One row per <b>London calendar day</b> of Octopus Agile half-hourly prices. For each day you get the <b>highest</b>, <b>lowest</b> and <b>average</b> slot price (pence per kWh, including VAT), how many <b>hours</b> that day were below 0p, and two columns against the <b>long-term trend</b> (the Since start line): <b>% above/below LT trend</b> and <b>standard deviation from trend</b>.</p>
<p>
<b>Avg −1y / −2y / −3y</b> are the daily <b>average</b> on the <b>same calendar date</b> one, two, and three years earlier (for example 23 Sep 2026 looks up 23 Sep 2025). They come only from days already in this table — a dash means that prior date is not stored yet (keep fetching over time), or that the date cannot exist (29 Feb in a non-leap year). These columns are table-only; the chart is unchanged.</p>
<p>
Toggle <b>Import (household)</b> / <b>Export (outgoing)</b> to switch series. The tariff codes are the ones typed on <b>Forecasts</b>. <b>Fetch year</b> asks Octopus for the public unit-rate history (around 370 days). Those half-hour slots go into <code>agile_price_snapshots</code>; the daily high / low / average go into <code>agile_year_daily</code> so the tab can reload from the database and the since-start trend can grow beyond one fetch. On PostgreSQL the owner must run the Setup &amp; Info CREATE script once so that new table exists (the dashboard login is not allowed to create it).</p>
<p>
<b>Hours below 0p</b> is the sum of slot lengths whose price is strictly less than 0p. A normal Agile slot is 30 minutes, so seven cheap slots are 3.5 hours. Days with no negative slots show a dash. Clock-change days can have 46 or 50 slots instead of 48 — the hour count still uses each slot’s real length.</p>
<p>
Days Octopus did not return, and days with only a handful of slots (a leftover standing rate or a timezone spill, not a real day of prices), are <b>left out</b>, not guessed. That keeps the right-hand end of the chart aligned with the table. If you changed Agile product mid-year, only history for the <i>current</i> product/tariff on Forecasts will appear from the API; older stored days for that same tariff stay in the table.</p>
<p>
<b>Trend</b> checkboxes overlay linear fits of the daily average — they are labelled analysis lines, not measurements: <b>Monthly</b> (one fit per calendar month), <b>YTD</b> (1 January of the latest year through the last day), <b>Yearly</b> (last 365 days), <b>Since start</b> (every stored day — this is the LT trend the table uses). Drag the table column borders to resize; widths are remembered.</p>
<p>
<b>% above/below LT trend</b> is how far that day’s average sits from the since-start line, as a percentage of the line’s value that day (positive = more expensive than the trend). <b>Std. deviation from trend</b> is the same gap in standard deviations of the residuals (σ). Near-zero trend days show a dash instead of an exploding percentage.</p>
"""
