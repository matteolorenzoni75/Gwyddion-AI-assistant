"""
The slot contract.

A panel is one feature's worth of user interface. The main window knows nothing
about any particular panel -- it discovers them, docks them, and passes them a
shared context. Adding a feature later means writing a subclass and listing it;
it does not mean editing the window.

That is what "slots ready for the future" means concretely: roughness analysis,
artifact detection and the human-validation loop each become a Panel subclass,
and everything around them stays as it is.

A panel that is not ready yet can still be listed -- set `available = False`
and it appears disabled, with `unavailable_reason` shown in its place. Better
to show the shape of what is coming than to hide it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from afm_copilot.gui.workers import TaskRunner


@dataclass
class AppContext:
    """
    What every panel is given.

    Panels talk to each other only through this -- never by holding references
    to one another. A panel announces a new selection by calling
    `set_channel`; whoever cares has subscribed via `on_channel_changed`.
    """

    runner: "TaskRunner"
    log: Callable[[str], None]
    work_dir: Path

    # The scan currently under the cursor, as an afm_copilot.gwy_io.Channel.
    channel: Any | None = None
    channel_path: Path | None = None

    _channel_listeners: list[Callable[[Any, Path | None], None]] = \
        field(default_factory=list, repr=False)
    _files_listeners: list[Callable[[list[Path]], None]] = \
        field(default_factory=list, repr=False)

    # -- current channel ---------------------------------------------------
    def on_channel_changed(self, fn: Callable[[Any, Path | None], None]) -> None:
        self._channel_listeners.append(fn)

    def set_channel(self, channel: Any, path: Path | None = None) -> None:
        self.channel = channel
        self.channel_path = path
        for fn in list(self._channel_listeners):
            fn(channel, path)

    # -- the working set of files -----------------------------------------
    def on_files_changed(self, fn: Callable[[list[Path]], None]) -> None:
        self._files_listeners.append(fn)

    def set_files(self, files: list[Path]) -> None:
        for fn in list(self._files_listeners):
            fn(files)


class Panel(QWidget):
    """Base class for every dockable feature panel."""

    #: Shown in the dock title bar and the View menu.
    title: str = "Panel"

    #: "left", "right" or "bottom" -- where the window docks it by default.
    area: str = "right"

    #: False for a feature that is planned but not built yet.
    available: bool = True

    #: Explains the disabled state. Say what it will do, not just that it is missing.
    unavailable_reason: str = ""

    def __init__(self, context: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = context
        if self.available:
            self.build()
        else:
            self._build_placeholder()

    def build(self) -> None:
        """Construct the panel's widgets. Override this."""
        raise NotImplementedError

    def _build_placeholder(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        label = QLabel(self.unavailable_reason or "Not built yet.")
        label.setWordWrap(True)
        label.setStyleSheet("color: palette(mid);")
        layout.addWidget(label)
        layout.addStretch(1)
