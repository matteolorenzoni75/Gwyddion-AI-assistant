param(
    [string]$Root = "C:\AFM_Copilot"
)

$ErrorActionPreference = "Stop"

$OldRepo = "C:\AFM_image_wizard"
$OldData = "C:\AFM_Automation"
$OldCodexVenv = "C:\AFM_codex_venv"

$App = Join-Path $Root "app"
$Data = Join-Path $Root "data"
$Workspace = Join-Path $Root "workspace"
$Legacy = Join-Path $Root "legacy"
$Marker = Join-Path $Root ".layout-v2"

function Ensure-Directory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    } elseif (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Expected directory but found another item: $Path"
    }
}

function New-DirectoryJunction([string]$Link, [string]$Target) {
    if (Test-Path -LiteralPath $Link) {
        return
    }
    Ensure-Directory (Split-Path -Parent $Link)
    New-Item -ItemType Junction -Path $Link -Target $Target | Out-Null
}

function New-FileHardLink([string]$Link, [string]$Target) {
    if (Test-Path -LiteralPath $Link) {
        return
    }
    Ensure-Directory (Split-Path -Parent $Link)
    New-Item -ItemType HardLink -Path $Link -Target $Target | Out-Null
}

$script:OpaqueConflicts = @()

function Merge-TreeByLinks([string]$Source, [string]$Destination) {
    # Recovery-safe union of a partially moved tree.
    # Existing destination content wins. Missing directories become junctions
    # to the untouched source; missing files become hard links. No source data
    # are copied, deleted, renamed or permission-modified.
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        return
    }
    Ensure-Directory $Destination

    try {
        $children = @(Get-ChildItem -LiteralPath $Source -Force -ErrorAction Stop)
    } catch [System.UnauthorizedAccessException] {
        $script:OpaqueConflicts += [pscustomobject]@{
            source = $Source
            destination = $Destination
            reason = "access_denied_source_tree"
        }
        return
    } catch {
        if ($_.Exception.Message -match "access|denied|permission") {
            $script:OpaqueConflicts += [pscustomobject]@{
                source = $Source
                destination = $Destination
                reason = "source_tree_not_enumerable"
            }
            return
        }
        throw
    }

    $children | ForEach-Object {
        $src = $_.FullName
        $dst = Join-Path $Destination $_.Name

        if (-not (Test-Path -LiteralPath $dst)) {
            if ($_.PSIsContainer) {
                New-DirectoryJunction $dst $src
            } else {
                New-FileHardLink $dst $src
            }
            return
        }

        $dstItem = Get-Item -LiteralPath $dst -Force
        if ($_.PSIsContainer -and $dstItem.PSIsContainer) {
            # If destination is already a junction/reparse point, it already
            # represents a complete subtree; do not recurse through it.
            if (($dstItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
                Merge-TreeByLinks $src $dst
            }
            return
        }

        if (-not $_.PSIsContainer -and -not $dstItem.PSIsContainer) {
            # A partial Move-Item can leave the same file on both sides.
            # Accept only byte-identical duplicates; otherwise stop.
            if ($_.Length -ne $dstItem.Length) {
                throw "Conflicting files after partial migration: $src <> $dst"
            }
            $a = (Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash
            $b = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash
            if ($a -ne $b) {
                throw "Conflicting files after partial migration: $src <> $dst"
            }
            return
        }

        throw "File/directory type conflict after partial migration: $src <> $dst"
    }
}

function Move-IfSafe([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        return
    }
    if (Test-Path -LiteralPath $Destination) {
        return
    }
    Ensure-Directory (Split-Path -Parent $Destination)
    Move-Item -LiteralPath $Source -Destination $Destination
}

function Rewrite-TextPaths([string]$Base, $Map) {
    if (-not (Test-Path -LiteralPath $Base -PathType Container)) {
        return 0
    }
    $changedCount = 0
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    Get-ChildItem -LiteralPath $Base -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in ".json", ".jsonl" } |
        ForEach-Object {
            $path = $_.FullName
            $text = [System.IO.File]::ReadAllText($path)
            $new = $text
            foreach ($old in $Map.Keys) {
                $new = $new.Replace($old, $Map[$old])
                $new = $new.Replace(
                    $old.Replace("\", "\\"),
                    $Map[$old].Replace("\", "\\"))
            }
            if ($new -ne $text) {
                [System.IO.File]::WriteAllText($path, $new, $utf8)
                $changedCount++
            }
        }
    return $changedCount
}

if (Test-Path -LiteralPath $Marker) {
    Write-Host "AFM Copilot layout v2 is already active at $Root"
    exit 0
}

if (-not (Test-Path -LiteralPath $OldRepo -PathType Container) -and
    -not (Test-Path -LiteralPath $App -PathType Container)) {
    throw "Neither old nor consolidated AFM Copilot app directory exists."
}

Ensure-Directory $Root
Ensure-Directory $Legacy
Ensure-Directory $Data
Ensure-Directory $Workspace

# If the first migration attempt already moved the workspace, keep it.
# Otherwise move only this small controlled tree; never move the AFM archive.
$oldWorkspace = Join-Path $OldData "AFM_Copilot_Workspace"
if (-not (Test-Path -LiteralPath $Workspace -PathType Container) -or
    -not (Get-ChildItem -LiteralPath $Workspace -Force -ErrorAction SilentlyContinue)) {
    if (Test-Path -LiteralPath $oldWorkspace -PathType Container) {
        if (Test-Path -LiteralPath $Workspace) {
            Remove-Item -LiteralPath $Workspace -Force
        }
        Move-Item -LiteralPath $oldWorkspace -Destination $Workspace
    }
}

# Compact legacy workspace names idempotently.
$renames = [ordered]@{
    "02_Automatic_Results" = "runs"
    "03_Approved" = "approved"
    "04_Reports" = "reports"
    "05_Benchmark_Corpus" = "benchmark"
}
foreach ($name in $renames.Keys) {
    $src = Join-Path $Workspace $name
    $dst = Join-Path $Workspace $renames[$name]
    if (Test-Path -LiteralPath $src -PathType Container) {
        if (-not (Test-Path -LiteralPath $dst)) {
            Move-Item -LiteralPath $src -Destination $dst
        }
    }
}
foreach ($name in @("runs", "approved", "reports", "benchmark")) {
    Ensure-Directory (Join-Path $Workspace $name)
}

$oldReview = Join-Path $Workspace "01_Manual_To_Review"
if (Test-Path -LiteralPath $oldReview -PathType Container) {
    $legacyWorkspace = Join-Path $Legacy "workspace-old"
    Ensure-Directory $legacyWorkspace
    $reviewDest = Join-Path $legacyWorkspace "01_Manual_To_Review"
    if (-not (Test-Path -LiteralPath $reviewDest)) {
        Move-Item -LiteralPath $oldReview -Destination $reviewDest
    }
}

# IMPORTANT: do NOT move C:\AFM_Automation again.
# The previous attempt hit an ACL-protected archive directory. Build a single
# logical data view under C:\AFM_Copilot\data using existing partially moved
# content plus junctions/hardlinks to anything that remains in AFM_Automation.
Merge-TreeByLinks $OldData $Data

# Preserve the separate Codex environment. If it moves, keep a compatibility
# junction so any old absolute references continue to work.
if (Test-Path -LiteralPath $OldCodexVenv -PathType Container) {
    $codexDest = Join-Path $Legacy "AFM_codex_venv"
    if (-not (Test-Path -LiteralPath $codexDest)) {
        Move-Item -LiteralPath $OldCodexVenv -Destination $codexDest
        New-DirectoryJunction $OldCodexVenv $codexDest
    }
}

# Move the Git checkout only if it has not already moved. Then leave a
# compatibility junction at C:\AFM_image_wizard so moved venv/editable paths
# continue to resolve during verification.
if (-not (Test-Path -LiteralPath $App -PathType Container)) {
    Set-Location C:\
    Move-Item -LiteralPath $OldRepo -Destination $App
}
if (-not (Test-Path -LiteralPath $OldRepo)) {
    New-DirectoryJunction $OldRepo $App
}

# Back up path-bearing private state before rewriting absolute locations.
$private = Join-Path $env:USERPROFILE "AFM_Copilot_Private_Audits"
$backup = Join-Path $Legacy "private-path-backup"
Ensure-Directory $backup
if (Test-Path -LiteralPath $private -PathType Container) {
    Get-ChildItem -LiteralPath $private -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in ".json", ".jsonl", ".sqlite3" } |
        ForEach-Object {
            $relative = $_.FullName.Substring($private.Length).TrimStart("\")
            $dest = Join-Path $backup $relative
            Ensure-Directory (Split-Path -Parent $dest)
            if (-not (Test-Path -LiteralPath $dest)) {
                Copy-Item -LiteralPath $_.FullName -Destination $dest
            }
        }
}

$map = [ordered]@{
    "C:\AFM_Automation\AFM_Copilot_Workspace\02_Automatic_Results" = (Join-Path $Workspace "runs")
    "C:\AFM_Automation\AFM_Copilot_Workspace\03_Approved" = (Join-Path $Workspace "approved")
    "C:\AFM_Automation\AFM_Copilot_Workspace\04_Reports" = (Join-Path $Workspace "reports")
    "C:\AFM_Automation\AFM_Copilot_Workspace\05_Benchmark_Corpus" = (Join-Path $Workspace "benchmark")
    "C:\AFM_Automation\AFM_Copilot_Workspace" = $Workspace
    "C:\AFM_Automation" = $Data
    "C:\AFM_image_wizard" = $App
}

$privateChanged = Rewrite-TextPaths $private $map
$workspaceChanged = Rewrite-TextPaths $Workspace $map

# Rewrite the path column in the private label database.
$db = Join-Path $private "labeling\labels.sqlite3"
$python = Join-Path $App ".venv\Scripts\python.exe"
$dbChanged = 0
if (Test-Path -LiteralPath $db -PathType Leaf) {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Moved app has no .venv Python; SQLite path migration cannot continue."
    }
    $mapFile = Join-Path $Legacy "path-map.json"
    $map | ConvertTo-Json | Set-Content -LiteralPath $mapFile -Encoding UTF8
    $py = @'
import json, sqlite3, sys
db, mapping_file = sys.argv[1], sys.argv[2]
mapping = json.load(open(mapping_file, encoding="utf-8-sig"))
con = sqlite3.connect(db)
rows = con.execute("select scan_id, path from scans").fetchall()
changed = 0
for scan_id, path in rows:
    new = path
    for old, replacement in mapping.items():
        new = new.replace(old, replacement)
    if new != path:
        con.execute("update scans set path=? where scan_id=?", (new, scan_id))
        changed += 1
con.commit()
con.close()
print(changed)
'@
    $dbChanged = $py | & $python - $db $mapFile
}

# One launcher at the root.
$launcher = Join-Path $Root "AFM Copilot.bat"
$launcherText = '@echo off' + [Environment]::NewLine +
    'call "%~dp0app\AFM Copilot.bat"' + [Environment]::NewLine
[System.IO.File]::WriteAllText(
    $launcher, $launcherText, (New-Object System.Text.ASCIIEncoding))

[Environment]::SetEnvironmentVariable("AFM_COPILOT_HOME", $Root, "User")

[System.IO.File]::WriteAllText(
    $Marker,
    "AFM Copilot consolidated layout v2" + [Environment]::NewLine,
    (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "AFM Copilot consolidation completed."
Write-Host "Root:       $Root"
Write-Host "App:        $App"
Write-Host "Data view:  $Data"
Write-Host "Workspace:  $Workspace"
Write-Host "Legacy:     $Legacy"
Write-Host "Private JSON/JSONL files rewritten: $privateChanged"
Write-Host "Workspace JSON/JSONL files rewritten: $workspaceChanged"
Write-Host "SQLite scan paths rewritten: $dbChanged"
Write-Host "Opaque ACL conflicts preserved: $($script:OpaqueConflicts.Count)"
if ($script:OpaqueConflicts.Count -gt 0) {
    $conflictReport = Join-Path $Legacy "opaque-acl-conflicts.json"
    $script:OpaqueConflicts | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $conflictReport -Encoding UTF8
    Write-Host "ACL conflict report: $conflictReport"
}
Write-Host ""
Write-Host "IMPORTANT: C:\AFM_Automation may remain as backing storage for junctions."
Write-Host "Do not delete it yet. No archive permissions were changed and no raw data were copied."
Write-Host "Compatibility junction retained at C:\AFM_image_wizard during verification."
Write-Host "Launcher: $launcher"
