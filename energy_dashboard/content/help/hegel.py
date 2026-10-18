"""
Help text for HegelTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "HegelTab"

HELP_TEXT = """\
<h2>Hegel</h2>
<p>Hegel is a separate look at energy kit that already exists around a place, starting with Chinnor in Oxfordshire. It is not this house’s inverter, and it does not switch anything on or off.</p>
<p>The inventory is a PostgreSQL database named <b>hegel</b>, on the same server as the plant log. The plant log stays in its own database. Creating <b>hegel</b> is a one-off job for the database owner, using <b>hegel_postgres.sql</b>. This page does not create the database.</p>
<p>The yellow <b>Hegel</b> button on the bottom bar, to the left of Alarms, opens this page. The gap matches the gap between Alarms and Refresh Page. <b>Check inventory</b> is the only thing that reads the database. Nothing is fetched from PVOutput or any other site from this page.</p>
<p>Chinnor is a 5 km circle around a configured centre. <b>OX39</b> is the postcode district name. It is not a rooftop pin. Where a capacity is unknown, the inventory leaves it blank.</p>
"""
