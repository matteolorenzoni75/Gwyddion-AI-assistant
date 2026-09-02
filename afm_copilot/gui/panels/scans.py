"""
The scan list: choose a folder, pick a scan, see it.

Deliberately shows filename, size and roughness and nothing inferred from the
name. The user keeps their test set blind on purpose, so this panel must not
label a file "grating" or "noisy" because its name says so.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from afm_copilot.bridge import BridgeError, GwyBridge
from afm_copilot.gui.panels.base import Panel
from afm_copilot.gwy_io import load_height

RAW_SUFFIXES = {".ibw", ".tiff", ".tif", ".spm", ".jpk", ".sxm", ".top",
                ".stp", ".nid", ".mi", ".par", ".ezd", ".afm"}


class ScansPanel(Panel):
    title = "Scans"
    area = "left"

    def build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        row = QHBoxLayout()
        self.open_btn = QPushButton("Open folder...")
        self.open_btn.clicked.connect(self.choose_folder)
        row.addWidget(self.open_btn)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.clicked.connect(self._reload)
        row.addWidget(self.reload_btn)
        layout.addLayout(row)

        self.folder_label = QLabel("No folder open")
        self.folder_label.setWordWrap(True)
        self.folder_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(self.folder_label)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["File", "Size", "RMS"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.tree, 1)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(self.count_label)

        self._folder: Path | None = None
        self._converted: dict[Path, Path] = {}

    # ------------------------------------------------------------- loading
    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of scans")
        if folder:
            self.load_folder(Path(folder))

    def load_folder(self, folder: Path) -> None:
        self._folder = folder
        self.folder_label.setText(str(folder))
        self._reload()

    def _reload(self) -> None:
        if self._folder is None:
            return
        self.tree.clear()
        files = sorted(f for f in self._folder.iterdir()
                       if f.is_file()
                       and (f.suffix.lower() == ".gwy"
                            or f.suffix.lower() in RAW_SUFFIXES))
        for f in files:
            item = QTreeWidgetItem([f.name, f"{f.stat().st_size / 1e6:.1f} MB", ""])
            item.setData(0, Qt.UserRole, str(f))
            self.tree.addTopLevelItem(item)

        self.count_label.setText(f"{len(files)} file(s)")
        self.ctx.set_files(files)
        if files:
            self.ctx.log(f"Found {len(files)} scan(s) in {self._folder}")

    # ----------------------------------------------------------- selection
    def selected_paths(self) -> list[Path]:
        return [Path(i.data(0, Qt.UserRole)) for i in self.tree.selectedItems()]

    def _selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if len(items) != 1:
            return
        path = Path(items[0].data(0, Qt.UserRole))
        self.ctx.runner.submit(
            f"Loading {path.name}",
            self._load_channel, path,
            on_result=lambda ch, p=path, it=items[0]: self._loaded(ch, p, it),
            on_failed=lambda desc, msg: self.ctx.log(f"{desc}: {msg}"),
            on_progress=self.ctx.log,
        )

    def _load_channel(self, path: Path):
        """Convert through Gwyddion if needed, then read the height channel."""
        if path.suffix.lower() != ".gwy":
            cached = self._converted.get(path)
            if cached is None or not cached.exists():
                report = GwyBridge().convert_raw([path], self.ctx.work_dir / "_gwy")
                ok = [r for r in report["results"] if r["ok"]]
                if not ok:
                    raise BridgeError(report["results"][0].get("error", "conversion failed"))
                cached = Path(ok[0]["gwy"])
                self._converted[path] = cached
            path = cached
        return load_height(path)

    def _loaded(self, channel, path: Path, item: QTreeWidgetItem) -> None:
        item.setText(2, f"{channel.rms * 1e9:.2f} nm")
        self.ctx.set_channel(channel, path)
        self.ctx.log(
            f"{path.name}: {channel.xres}x{channel.yres} px over "
            f"{channel.xreal * 1e6:.2f} um, z range "
            f"{channel.z_range * 1e9:.2f} nm, RMS {channel.rms * 1e9:.2f} nm "
            f"(raw -- includes any tilt)")
