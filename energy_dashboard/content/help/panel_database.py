"""
Help text for PanelDatabaseTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "PanelDatabaseTab"

HELP_TEXT = """\
<h2>Panel database</h2><p>
This page is in <b>Physical Plant</b>, next to Roof layout.
It is the list of PV modules on this house. Each row is one module type:
who made it, the model, the rated watts, and the size.</p>
<p>
<b>Vmp</b> is the datasheet voltage at maximum power (the volts one module
is rated to produce while working). <b>Voc</b> is the open-circuit voltage.
<b>Imp</b> is the current at maximum power. Type those from the module
label or the datasheet. Leave a cell blank when you do not have the number.
A blank is not stored as 0 V, and the live string voltage from the inverter
is not copied into this table.</p>
<p>
<b>Add panel</b> starts a blank row. <b>Remove</b> deletes the selected
row. <b>Import from Spec Sheet</b> reads a module datasheet — a PDF, or a
photo of the page — and fills a row from what that sheet prints: the maker,
the model, the watts, Vmp, Voc, Imp, and the width and height. A figure that
is not on the sheet stays blank. If that model is already in the list, only
the empty cells are filled. A scan can take a little while; the line under
the table says which page is being read. <b>Save</b> keeps the list. Roof
layout’s panel menu uses these rows,
so a face’s kilowatts follow the watts you typed here. Until you save your
own list, the page shows the generic wattage presets Roof layout already used.</p>
"""
