"""Conservative AFM channel-role identification and operation compatibility.

Identification relies on channel title *and* physical units. When unclear,
we return 'unknown' rather than treating a phase/current channel as height.
These roles govern safe correction routing, not acquisition labeling.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Specific electrical and dynamic channels precede generic "height" keywords.
ROLE_HINTS = (
    ("current", ("current", "c-afm", "cafm", "tuna", "conductive"), ("a", "pa", "na", "ua")),
    ("potential", ("potential", "kpfm", "cpd", "surface potential", "voltage"), ("v", "mv")),
    ("phase", ("phase", "phase shift", "lock-in phase"), ("deg", "degree", "rad")),
    ("amplitude", ("amplitude", "ampl", "oscillation amplitude"), ("v", "mv", "nm", "pm", "m")),
    ("frequency", ("frequency", "frequency shift", "delta f", "df"), ("hz", "khz")),
    ("dissipation", ("dissipation", "energy loss"), ("ev", "j")),
    ("error", ("deflection error", "height error", "error signal", "amplitude error",
               "feedback error", "z error"), ("v", "mv", "nm", "pm", "m", "a")),
    ("deflection", ("deflection", "force"), ("v", "mv", "n", "nn")),
    ("height", ("height", "topography", "topo", "z sensor", "z-sensor"), ("m", "nm", "um", "pm")),
)

HEIGHT_OPS = frozenset({
    "plane_level", "level_rotate", "facet_level", "polynomial_background",
    "flatten_base", "background_around_objects", "plane_around_objects",
    "fix_zero", "zero_mean",
})
# These might be appropriate for other signals but must be separately validated.
CONDITIONAL_OPS = frozenset({
    "align_rows_median_diff", "remove_scars", "mark_outliers",
    "interpolate_under_mask",
})


@dataclass(frozen=True)
class ChannelRole:
    role: str
    confidence: str
    physical_unit: str
    separate_processing: bool
    note: str

    def to_dict(self):
        return {
            "role": self.role, "confidence": self.confidence,
            "physical_unit": self.physical_unit,
            "separate_processing": self.separate_processing,
            "note": self.note,
        }


def identify_channel(title: str, unit: str = "") -> ChannelRole:
    name = re.sub(r"[\s_-]+", " ", (title or "").casefold()).strip()
    u = (unit or "").casefold().replace("µ", "u").replace("μ", "u").strip()
    # A vague channel name must never cause a non-height signal to be scaled in nm.
    for role, words, units in ROLE_HINTS:
        if any(word in name for word in words):
            if u and u not in units:
                return ChannelRole("unknown", "low", unit, True,
                                   "Channel title and unit disagree; manual review")
            return ChannelRole(role, "high" if u else "medium", unit, True,
                               "Role inferred from channel title and unit")
    return ChannelRole("unknown", "low", unit, True,
                       "Unrecognized channel: retain without height processing")


def operation_policy(channel_role: str, operation_key: str) -> dict:
    if channel_role == "height":
        return {"decision": "eligible_for_height_review",
                "reason": "Height operation still needs per-image safety gate"}
    if operation_key in HEIGHT_OPS:
        return {"decision": "blocked",
                "reason": "Topography-specific level, zero or background fit must not be applied to this signal"}
    if operation_key in CONDITIONAL_OPS:
        return {"decision": "review",
                "reason": "Non-height signal requires dedicated calibrated processing policy"}
    return {"decision": "review",
            "reason": "Unknown operation/channel combination: do not run automatically"}
