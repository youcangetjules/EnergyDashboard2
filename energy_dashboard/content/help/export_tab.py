"""
Help text for ExportTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "ExportTab"

HELP_TEXT = """\
<h2>Export</h2><p>
Builds a 30-min sliding-window <code>.xlsx</code> workbook centred on <i>now</i> (default ±1.5 days) with columns for spot price (Agile import &amp; export), historic consumption, the weekday × half-hour median usage prediction, and SOC.</p>
<p>
<b>Tips:</b> tweak the half-window and lookback weeks before Preview; enable backfill to fill the past portion with predictions where actual readings are missing. The workbook includes a README sheet describing every column.</p>
"""
