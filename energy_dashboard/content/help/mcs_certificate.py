"""
Help text for McsCertificateTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "McsCertificateTab"

HELP_TEXT = """\
<h2>MCS certificate</h2><p>
This page is in <b>Physical Plant</b>, next to Panel database.
An MCS certificate is the paperwork for the solar installation:
how many panels were fitted, the total kilowatts, the commissioning
date, and the installer. It is the record of the plant. It is not a
live voltage, and the app does not scale any chart from it.</p>
<p>
<b>Upload certificate</b> copies a PDF or a photo into this app.
The file window lists a memory stick on the left, and on Computer beside
the system disk.
The copy stays on this computer, under your PowerModel settings,
and it is not part of the program files. <b>Open</b> shows that copy
in your usual viewer. <b>Remove</b> deletes only the copy kept here.</p>
<p>
<b>Read certificate</b> runs as soon as a file is uploaded.
It fills the certificate number, the panel total, the installed kilowatts,
the commissioning date, and the installer from what is printed.
A digital PDF is read directly. A scan or a photo is read as a picture,
which takes longer. Mounting rails are not counted as panels.
The certificate does not say how the panels are split between the two
strings, and it does not print the panel voltages, so those are left alone.
You can still change a figure and press <b>Save details</b>.
String voltage still draws the volts the inverter reported.</p>
"""
