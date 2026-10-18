"""
Help text for StringDesignTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "StringDesignTab"

HELP_TEXT = """\
<h2>String design</h2><p>
This page is in <b>Physical Plant</b>. A scenario is a design: how many
panels are wired in series on string 1, and how many on string 2.
The two arrangements already listed are 6 and 6, and 7 and 5.
Add another if you want to try a different length.</p>
<p>
The panel comes from <b>Panel database</b>. <b>Vmp</b> is the voltage at
rated power. <b>Voc</b> is the open-circuit voltage in that same 25°C test.
Panels in series add those voltages. The current stays at <b>Imp</b>.
Six panels at 42.4 V work near 254 V and are open-circuit near 301 V.</p>
<p>
The three inverter figures are the MPPT’s lowest voltage, its highest
operating voltage, and the absolute maximum PV voltage. Type them from
the inverter datasheet. A blank is not filled in for you. A design is
inside the window only for the limits you have typed.</p>
<p>
Open-circuit voltage rises when the cells are cold. Type the panel’s
Voc temperature coefficient (percent per degree, a small negative number)
and tick <b>Cold morning</b> with the cell temperature you want to design
for. Until that is filled in, a cold morning is not checked, even if the
25°C voltage looks safe. <b>Hot cells</b> does the same for the working
voltage, which falls as the cells warm up.</p>
<p>
This page is a design calculation. It does not change the measured volts
on String voltage.</p>
"""
