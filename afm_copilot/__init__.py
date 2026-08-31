"""
AFM Copilot -- make Gwyddion's full capability reachable without knowing it.

The package is deliberately split so that the Python 2.7 dependency stays in
one place:

    bridge   Python 3 -> Python 2.7 PyGwy, over JSON. The only module that
             knows Gwyddion's install layout exists.
    gwy_io   Reads .gwy natively in Python 3, no subprocess.
    render   Publication-quality images: shared colour scale, scale bar, DPI.
    explain  Every operation carries a plain-language what/why/when-not.
"""

__version__ = "0.1.0"

from afm_copilot.bridge import BridgeConfig, BridgeError, GwyBridge

__all__ = ["BridgeConfig", "BridgeError", "GwyBridge", "__version__"]
