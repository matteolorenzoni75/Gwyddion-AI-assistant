# run_py27.ps1 -- run a PyGwy (Python 2.7) script with Gwyddion's libraries on the path.
#
# Usage:
#   .\tools\run_py27.ps1 .\tools\introspect_pygwy.py
#
# Why this exists: gwy.pyd lives in Gwyddion's bin directory and links against the
# GTK/GLib DLLs beside it, so both PATH and PYTHONPATH must point there before
# `import gwy` will succeed from a standalone Python 2.7 interpreter.
#
# Verified on this machine: Gwyddion 2.70 (32-bit) + Python 2.7.16 (32-bit).
# Gwyddion registers its process modules on import, so no GUI is needed.

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Script,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$GwyRoot = $env:GWYDDION_ROOT
if (-not $GwyRoot) { $GwyRoot = "C:\Program Files (x86)\Gwyddion" }

$Py27 = $env:PYTHON27
if (-not $Py27) { $Py27 = "C:\Python27\python.exe" }

if (-not (Test-Path $GwyRoot)) { throw "Gwyddion not found at $GwyRoot. Set GWYDDION_ROOT." }
if (-not (Test-Path $Py27))    { throw "Python 2.7 not found at $Py27. Set PYTHON27." }

$GwyBin   = Join-Path $GwyRoot "bin"
$GwyPygwy = Join-Path $GwyRoot "share\gwyddion\pygwy"

$env:PATH = "$GwyBin;$env:PATH"
$env:PYTHONPATH = "$GwyBin;$GwyPygwy"
$env:GWYDDION_ROOT = $GwyRoot

# PyGwy prints harmless GType registration warnings to stderr on import; they are
# noise from the GLib/GIO type system, not errors, so we let them through but
# they can be ignored.
& $Py27 $Script @ScriptArgs
exit $LASTEXITCODE
