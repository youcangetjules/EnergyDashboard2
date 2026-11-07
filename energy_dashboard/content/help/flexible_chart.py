"""
Help text for Flexible Chart (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "FlexibleChartTab"

HELP_TEXT = """\
<h2>Flexible Chart</h2>
<p>A general-purpose chart view for plotting any database column against any other.</p>

<p><b>Builder mode</b> lets you pick a table, columns, optional WHERE and ORDER BY
clauses, and a row limit. The tab constructs the SQL for you.</p>

<p><b>SQL mode</b> lets you type any SELECT query directly, including JOINs,
computed columns, and aggregates. Only read-only queries (SELECT / WITH) are
allowed.</p>

<p><b>Templates</b> offer preset queries for common use cases (spend over time,
SOC history, PV vs load, etc.). Selecting a template fills the SQL editor.</p>

<p>After running a query, assign columns to the <b>X axis</b> and one or more
<b>Y axis</b> series, choose a chart type (Line, Scatter, Bar, Step, Area),
and click <b>Draw</b>.</p>

<p>Click <b>+Y</b> to overlay additional columns on the same chart.</p>

<p><i>Note:</i> Templates use SQLite syntax by default. If your primary database
is PostgreSQL, you may need to adjust date functions
(e.g. <code>NOW() - INTERVAL '7 days'</code> instead of
<code>datetime('now', '-7 days')</code>).</p>
"""
