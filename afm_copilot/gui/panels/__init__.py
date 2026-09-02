"""
The panel registry.

`PANELS` is the whole extension point. To add a feature, write a Panel
subclass and put it in this list -- the main window docks it, wires it to the
shared context, and adds it to the View menu without knowing what it is.
"""

from afm_copilot.gui.panels.base import AppContext, Panel
from afm_copilot.gui.panels.planned import (DetectorsPanel, LearningPanel,
                                            RoughnessPanel)
from afm_copilot.gui.panels.profile import ProfilePanel
from afm_copilot.gui.panels.recipes import RecipesPanel
from afm_copilot.gui.panels.scans import ScansPanel

#: Order matters only for where docks stack.
PANELS: list[type[Panel]] = [
    ScansPanel,
    RecipesPanel,
    ProfilePanel,
    RoughnessPanel,
    DetectorsPanel,
    LearningPanel,
]

__all__ = ["AppContext", "Panel", "PANELS", "ScansPanel", "RecipesPanel",
           "ProfilePanel", "RoughnessPanel", "DetectorsPanel", "LearningPanel"]
