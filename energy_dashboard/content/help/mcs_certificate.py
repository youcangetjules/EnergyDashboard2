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
The copy stays on this computer, under your PowerModel settings,
and it is not part of the program files. <b>Open</b> shows that copy
in your usual viewer. <b>Remove</b> deletes only the copy kept here.</p>
<p>
Type the figures off the certificate and press <b>Save details</b>.
Total panels is the number printed for the whole installation.
Leave a figure blank if the certificate does not show it.
String voltage still draws the volts the inverter reported.</p>
"""
