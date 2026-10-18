"""File window used by Upload, Open, and Save.

On Linux the built-in Computer page only lists ``/``. A memory stick mounted
under ``/media``, ``/run/media``, or ``/mnt`` is a real drive and was missing.
The same window draws Cancel in the bottom-right, under the resize grip, so
the button's border does not close. This helper lists those sticks and keeps
Cancel clear of the grip.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QIdentityProxyModel, QModelIndex, QStandardPaths, QStorageInfo, QUrl
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QTreeView,
)

# The resize grip sits in the dialog corner and covers the last few pixels of
# Cancel when the button box uses the stock 11px margin.
_CORNER_RIGHT = 22
_CORNER_BOTTOM = 26


def choose_open_file(parent, title: str, directory: str = "", name_filter: str = "") -> str:
    """Ask for an existing file. Empty string if cancelled."""
    return _choose(parent, title, directory, name_filter, save=False)


def choose_save_file(parent, title: str, directory: str = "", name_filter: str = "") -> str:
    """Ask where to save a file. Empty string if cancelled."""
    return _choose(parent, title, directory, name_filter, save=True)


def mounted_user_volumes() -> list[str]:
    """Mounts a person would call a drive: memory sticks and disks under media or mnt."""
    found: list[str] = []
    seen: set[str] = set()
    for vol in QStorageInfo.mountedVolumes():
        if not vol.isValid() or not vol.isReady():
            continue
        root = Path(vol.rootPath())
        try:
            key = str(root.resolve())
        except OSError:
            continue
        if key in seen or key == "/":
            continue
        if not _is_user_volume(Path(key)):
            continue
        if not Path(key).is_dir():
            continue
        seen.add(key)
        found.append(key)
    return found


def _is_user_volume(path: Path) -> bool:
    parts = path.parts
    if len(parts) < 3:
        return False
    if parts[1] in ("media", "mnt"):
        return True
    return parts[1] == "run" and len(parts) >= 4 and parts[2] == "media"


class _ComputerDrives(QIdentityProxyModel):
    """Add memory sticks as rows next to ``/`` on the Computer page.

    The stock model has a single root row, ``/``. These extra rows use a small
    internal id (1, 2, …). A real file's id is a pointer, so the two do not meet.
    """

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self.paths = list(paths)

    def _base_rows(self) -> int:
        return QIdentityProxyModel.rowCount(self, QModelIndex())

    def _extra_slot(self, proxy: QModelIndex):
        if not proxy.isValid():
            return None
        key = int(proxy.internalId())
        if proxy.row() < self._base_rows():
            return None
        if 1 <= key <= len(self.paths):
            return key - 1
        return None

    def rowCount(self, parent=QModelIndex()):
        count = QIdentityProxyModel.rowCount(self, parent)
        if not parent.isValid():
            return count + len(self.paths)
        return count

    def index(self, row, column, parent=QModelIndex()):
        if not parent.isValid():
            base = self._base_rows()
            if row >= base:
                return self.createIndex(row, column, row - base + 1)
        return QIdentityProxyModel.index(self, row, column, parent)

    def parent(self, child):
        if self._extra_slot(child) is not None:
            return QModelIndex()
        return QIdentityProxyModel.parent(self, child)

    def mapToSource(self, proxy):
        slot = self._extra_slot(proxy)
        if slot is None:
            return QIdentityProxyModel.mapToSource(self, proxy)
        src0 = self.sourceModel().index(self.paths[slot])
        if proxy.column() == 0 or not src0.isValid():
            return src0
        return self.sourceModel().index(src0.row(), proxy.column(), src0.parent())

    def flags(self, index):
        if self._extra_slot(index) is not None:
            return self.sourceModel().flags(self.mapToSource(index))
        return QIdentityProxyModel.flags(self, index)

    def hasChildren(self, parent=QModelIndex()):
        if self._extra_slot(parent) is not None:
            return self.sourceModel().hasChildren(self.mapToSource(parent))
        return QIdentityProxyModel.hasChildren(self, parent)

    def sibling(self, row, column, idx):
        if self._extra_slot(idx) is not None:
            return self.index(row, column, QModelIndex())
        return QIdentityProxyModel.sibling(self, row, column, idx)


def _sidebar_urls(volumes: list[str]) -> list[QUrl]:
    urls = [QUrl("file:")]
    seen = {""}
    for vol in volumes:
        if vol not in seen:
            urls.append(QUrl.fromLocalFile(vol))
            seen.add(vol)
    home = str(Path.home())
    if home not in seen:
        urls.append(QUrl.fromLocalFile(home))
        seen.add(home)
    for loc in (
        QStandardPaths.StandardLocation.DesktopLocation,
        QStandardPaths.StandardLocation.DocumentsLocation,
        QStandardPaths.StandardLocation.DownloadLocation,
        QStandardPaths.StandardLocation.PicturesLocation,
    ):
        folder = QStandardPaths.writableLocation(loc)
        if folder and folder not in seen and Path(folder).is_dir():
            urls.append(QUrl.fromLocalFile(folder))
            seen.add(folder)
    return urls


def _keep_cancel_clear(dlg: QFileDialog) -> None:
    lay = dlg.layout()
    if lay is not None:
        margin = lay.contentsMargins()
        lay.setContentsMargins(
            margin.left(),
            margin.top(),
            max(margin.right(), _CORNER_RIGHT),
            max(margin.bottom(), _CORNER_BOTTOM),
        )
    box = dlg.findChild(QDialogButtonBox)
    if box is not None:
        box.setContentsMargins(2, 2, 8, 6)


def _attach_volumes(dlg: QFileDialog, volumes: list[str]) -> None:
    tree = dlg.findChild(QTreeView, "treeView")
    source = tree.model() if tree is not None else None
    if source is None:
        return
    # The dialog may already have wrapped the file model. Use the file model.
    file_model = source.sourceModel() if hasattr(source, "sourceModel") else None
    if file_model is None:
        file_model = source
    proxy = _ComputerDrives(volumes, dlg)
    proxy.setSourceModel(file_model)
    dlg.setProxyModel(proxy)


def _start_folder(directory: str) -> tuple[str, str]:
    """Folder to open, and a file name to offer when the caller passed one."""
    raw = (directory or "").strip()
    if not raw:
        return str(Path.home()), ""
    path = Path(raw).expanduser()
    if path.is_dir():
        return str(path), ""
    parent = path.parent
    if str(parent) in ("", "."):
        folder = str(Path.cwd())
    elif parent.is_dir():
        folder = str(parent)
    else:
        folder = str(Path.home())
    if path.is_file() or path.suffix:
        return folder, path.name
    return folder, ""


def _choose(parent, title: str, directory: str, name_filter: str, *, save: bool) -> str:
    start, suggested = _start_folder(directory)
    dlg = QFileDialog(parent, title, start, name_filter)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    if save:
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dlg.setFileMode(QFileDialog.FileMode.AnyFile)
    else:
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
    volumes = mounted_user_volumes()
    dlg.setSidebarUrls(_sidebar_urls(volumes))
    if volumes:
        _attach_volumes(dlg, volumes)
    # The drive rows reset the view to Computer. Put the window back in the
    # folder we were asked to open; Computer still lists the sticks.
    dlg.setDirectory(start)
    if suggested:
        dlg.selectFile(suggested)
    _keep_cancel_clear(dlg)
    try:
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        chosen = ""
        if accepted:
            files = dlg.selectedFiles()
            chosen = files[0] if files else ""
        return chosen
    finally:
        # Drop the proxy before the dialog is destroyed. Leaving it attached
        # has crashed Qt while the window shuts down.
        dlg.setProxyModel(None)
