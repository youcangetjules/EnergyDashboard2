"""
Energy Dashboard — `ui/columns.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
_COLWIDTH_QS_ORG = "PowerModel"
_COLWIDTH_QS_APP = "EnergyDashboard2"


def _colwidth_base(settings_key: str) -> str:
    return f"ui/colwidth/{settings_key}"


def qtable_prepare_interactive_columns(table: QTableWidget) -> None:
    hdr = table.horizontalHeader()
    hdr.setStretchLastSection(False)
    for c in range(table.columnCount()):
        hdr.setSectionResizeMode(c, QHeaderView.Interactive)


def qtable_restore_column_widths(
    table: QTableWidget, settings_key: str, *, resize_if_no_saved: bool = False,
) -> bool:
    """Return True if widths were applied from QSettings."""
    if table.columnCount() <= 0:
        return False
    s = QSettings(_COLWIDTH_QS_ORG, _COLWIDTH_QS_APP)
    base = _colwidth_base(settings_key)
    n = table.columnCount()
    saved_n = int(s.value(f"{base}/_ncols", -1, type=int))
    if saved_n != n:
        if resize_if_no_saved:
            table.resizeColumnsToContents()
        return False
    for c in range(n):
        w = s.value(f"{base}/c{c}", None, type=int)
        if w is not None and int(w) >= 12:
            table.setColumnWidth(c, int(w))
    return True


def qtable_save_column_widths(table: QTableWidget, settings_key: str) -> None:
    if table.columnCount() <= 0:
        return
    s = QSettings(_COLWIDTH_QS_ORG, _COLWIDTH_QS_APP)
    base = _colwidth_base(settings_key)
    hdr = table.horizontalHeader()
    n = table.columnCount()
    s.setValue(f"{base}/_ncols", n)
    for c in range(n):
        s.setValue(f"{base}/c{c}", int(hdr.sectionSize(c)))
    try:
        s.sync()
    except Exception:
        pass


def qtable_attach_column_width_persistence(table: QTableWidget) -> None:
    if getattr(table, "_qcol_persist_attached", False):
        return
    table._qcol_persist_attached = True
    hdr = table.horizontalHeader()
    timer = QTimer(table)
    timer.setSingleShot(True)
    timer.setInterval(450)

    tw = weakref.ref(table)

    def flush():
        t = tw()
        if t is None:
            return
        key = getattr(t, "_qcol_persist_key", None)
        if key:
            qtable_save_column_widths(t, key)

    timer.timeout.connect(flush)
    hdr.sectionResized.connect(lambda *_a: timer.start())
    app = QApplication.instance()
    if app is not None:
        # Without this, a resize followed by quit within the debounce window never
        # calls setValue — column widths (e.g. Connectivity Status) were lost.
        app.aboutToQuit.connect(flush)


def qtable_set_column_width_key(table: QTableWidget, settings_key: str) -> None:
    table._qcol_persist_key = settings_key


def qtree_prepare_interactive_columns(tree: QTreeWidget) -> None:
    hdr = tree.header()
    hdr.setStretchLastSection(False)
    for c in range(tree.columnCount()):
        hdr.setSectionResizeMode(c, QHeaderView.Interactive)


def qtree_restore_column_widths(
    tree: QTreeWidget, settings_key: str, *, resize_if_no_saved: bool = False,
) -> bool:
    if tree.columnCount() <= 0:
        return False
    s = QSettings(_COLWIDTH_QS_ORG, _COLWIDTH_QS_APP)
    base = _colwidth_base(settings_key)
    n = tree.columnCount()
    saved_n = int(s.value(f"{base}/_ncols", -1, type=int))
    if saved_n != n:
        if resize_if_no_saved:
            for c in range(n):
                tree.resizeColumnToContents(c)
        return False
    for c in range(n):
        w = s.value(f"{base}/c{c}", None, type=int)
        if w is not None and int(w) >= 12:
            tree.setColumnWidth(c, int(w))
    return True


def qtree_save_column_widths(tree: QTreeWidget, settings_key: str) -> None:
    if tree.columnCount() <= 0:
        return
    s = QSettings(_COLWIDTH_QS_ORG, _COLWIDTH_QS_APP)
    base = _colwidth_base(settings_key)
    hdr = tree.header()
    n = tree.columnCount()
    s.setValue(f"{base}/_ncols", n)
    for c in range(n):
        s.setValue(f"{base}/c{c}", int(hdr.sectionSize(c)))
    try:
        s.sync()
    except Exception:
        pass


def qtree_attach_column_width_persistence(tree: QTreeWidget) -> None:
    if getattr(tree, "_qcol_persist_attached", False):
        return
    tree._qcol_persist_attached = True
    hdr = tree.header()
    timer = QTimer(tree)
    timer.setSingleShot(True)
    timer.setInterval(450)

    tr = weakref.ref(tree)

    def flush():
        t = tr()
        if t is None:
            return
        key = getattr(t, "_qcol_persist_key", None)
        if key:
            qtree_save_column_widths(t, key)

    timer.timeout.connect(flush)
    hdr.sectionResized.connect(lambda *_a: timer.start())
    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(flush)


def qtree_set_column_width_key(tree: QTreeWidget, settings_key: str) -> None:
    tree._qcol_persist_key = settings_key


__all__ = [n for n in globals() if not n.startswith('__')]
