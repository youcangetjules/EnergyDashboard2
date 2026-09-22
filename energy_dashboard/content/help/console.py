"""
Help text for ConsoleTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "ConsoleTab"

HELP_TEXT = """\
<h2>Console</h2><p>
Tailing log of every <code>_log.info()</code> / <code>_log.warn()</code> / <code>_log.err()</code> call across the app. Persists across restarts via a JSONL file (auto-trimmed). <b>Clear</b> wipes both the in-memory ring and the on-disk file.</p>
<p>
<b>Auto-scroll</b> keeps the newest lines in view (tick it on if the view is frozen). Leave it off while reading older entries.</p>
<p>
<b>RS485 / Modbus</b> traffic from Setup → Test Modbus, Connectivity’s local Modbus probe, and Console <b>RS485 heartbeat</b> is tagged <code>RS485</code>. Heartbeat is a repeating ping (gateway TCP + one holding-register read) using the Setup Modbus target; interval 10–120&nbsp;s. Keep <b>Debug</b> checked for per-register Test Modbus tries. Tick <b>RS485 only</b> to hide every other source.</p>
"""
