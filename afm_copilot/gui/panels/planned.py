"""
The slots that are not filled yet.

These appear in the window, disabled, saying what they will do. Showing the
shape of what is coming is more useful than hiding it: it tells you where a
feature will live, and it keeps the layout honest about what the tool does and
does not do today.

Filling one in means giving it a `build()` and setting `available = True`.
Nothing else changes -- not the window, not the other panels.
"""

from __future__ import annotations

from afm_copilot.gui.panels.base import Panel


class RoughnessPanel(Panel):
    title = "Roughness"
    area = "right"
    available = False
    unavailable_reason = (
        "Roughness and spatial length.\n\n"
        "Will report Sa, Sq and the ISO 25178 family, fit the power spectral "
        "density to recover correlation length and fractal dimension, and pool "
        "several surfaces into one answer.\n\n"
        "It will also report the levelling bias: every flattening step lowers "
        "measured roughness by a calculable amount, so a raw Sq quoted after "
        "processing is always an underestimate. Getting that right is the "
        "reason this panel is not a simple standard-deviation readout."
    )


class DetectorsPanel(Panel):
    title = "Artifacts"
    area = "right"
    available = False
    unavailable_reason = (
        "Automatic artifact detection.\n\n"
        "Will name what is wrong with a scan before anything is done to it: "
        "residual tilt and bow, row banding, scars, spikes, and periodic noise "
        "at any angle -- then recommend a recipe and say why.\n\n"
        "The hard part is telling genuine periodic structure from periodic "
        "noise. The 500-sample synthetic set already carries that label, "
        "including 81 scans that contain both at once, so the detector can be "
        "tested against known answers rather than judged by eye."
    )


class LearningPanel(Panel):
    title = "Learning"
    area = "right"
    available = False
    unavailable_reason = (
        "Learning from your decisions, with you in the loop.\n\n"
        "Will show what the system proposes for a scan and let you accept, "
        "correct or reject it. Those judgements become the training data.\n\n"
        "This panel is the reason the application exists rather than only the "
        "conversational interface: approving or correcting a decision means "
        "looking at the image and clicking, which does not work well in chat."
    )


PLANNED_PANELS = [RoughnessPanel, DetectorsPanel, LearningPanel]
