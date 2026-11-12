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

function Move-CheckedDirectory([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        return
    }
    if (Test-Path -LiteralPath $Destination) {
        throw "Destination already exists: $Destination"
    }
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
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
                $new = $new.Replace($old.Replace("\", "\\"), $Map[$old].Replace("\", "\\"))
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

if (-not (Test-Path -LiteralPath $OldRepo -PathType Container)) {
    throw "Expected current repository not found: $OldRepo"
}

New-Item -ItemType Directory -Force -Path $Root | Out-Null
New-Item -ItemType Directory -Force -Path $Legacy | Out-Null

# Preserve anything that already lived in C:\AFM_Copilot before consolidation.
$pre = Join-Path $Legacy "pre-consolidation"
New-Item -ItemType Directory -Force -Path $pre | Out-Null
Get-ChildItem -LiteralPath $Root -Force |
    Where-Object { $_.Name -ne "legacy" -and $_.Name -ne ".layout-v2" } |
    ForEach-Object {
        $dest = Join-Path $pre $_.Name
        if (Test-Path -LiteralPath $dest) {
            throw "Cannot preserve existing AFM_Copilot content because destination exists: $dest"
        }
        Move-Item -LiteralPath $_.FullName -Destination $dest
    }

# Extract the active workspace from the old data tree first.
$oldWorkspace = Join-Path $OldData "AFM_Copilot_Workspace"
Move-CheckedDirectory $oldWorkspace $Workspace

# Compact old workspace names without deleting anything.
if (Test-Path -LiteralPath $Workspace -PathType Container) {
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
            if (Test-Path -LiteralPath $dst) {
                throw "Workspace target already exists: $dst"
            }
            Move-Item -LiteralPath $src -Destination $dst
        }
    }

    $oldReview = Join-Path $Workspace "01_Manual_To_Review"
    if (Test-Path -LiteralPath $oldReview -PathType Container) {
        $legacyWorkspace = Join-Path $Legacy "workspace-old"
        New-Item -ItemType Directory -Force -Path $legacyWorkspace | Out-Null
        Move-Item -LiteralPath $oldReview -Destination (Join-Path $legacyWorkspace "01_Manual_To_Review")
    }
}

# The remaining AFM_Automation tree becomes the single data tree.
Move-CheckedDirectory $OldData $Data

# Preserve the old separate Codex environment; do not delete it yet.
if (Test-Path -LiteralPath $OldCodexVenv -PathType Container) {
    Move-CheckedDirectory $OldCodexVenv (Join-Path $Legacy "AFM_codex_venv")
}

# Move the Git checkout last, after leaving its working directory.
Set-Location C:\
Move-CheckedDirectory $OldRepo $App

# Compact directories should always exist.
foreach ($folder in @(
    $Data,
    $Workspace,
    (Join-Path $Workspace "runs"),
    (Join-Path $Workspace "approved"),
    (Join-Path $Workspace "reports"),
    (Join-Path $Workspace "benchmark")
)) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
}

# Back up path-bearing private state before rewriting absolute locations.
$private = Join-Path $env:USERPROFILE "AFM_Copilot_Private_Audits"
$backup = Join-Path $Legacy "private-path-backup"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
if (Test-Path -LiteralPath $private -PathType Container) {
    Get-ChildItem -LiteralPath $private -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in ".json", ".jsonl", ".sqlite3" } |
        ForEach-Object {
            $relative = $_.FullName.Substring($private.Length).TrimStart("\")
            $dest = Join-Path $backup $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
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
    "C:\AFM_codex_venv" = (Join-Path $Legacy "AFM_codex_venv")
}

$privateChanged = Rewrite-TextPaths $private $map
$workspaceChanged = Rewrite-TextPaths $Workspace $map

# Rewrite the path column in the private label database.
$db = Join-Path $private "labeling\labels.sqlite3"
$python = Join-Path $App ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $db -PathType Leaf) {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Moved app has no .venv Python; private SQLite path migration was not attempted."
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
} else {
    $dbChanged = 0
}

# One obvious launcher at the single root.
$launcher = Join-Path $Root "AFM Copilot.bat"
$launcherText = '@echo off' + [Environment]::NewLine +
    'call "%~dp0app\AFM Copilot.bat"' + [Environment]::NewLine
[System.IO.File]::WriteAllText(
    $launcher, $launcherText, (New-Object System.Text.ASCIIEncoding))

# Persist the chosen root for future shells; code also defaults to this path.
[Environment]::SetEnvironmentVariable("AFM_COPILOT_HOME", $Root, "User")

[System.IO.File]::WriteAllText(
    $Marker,
    "AFM Copilot consolidated layout v2" + [Environment]::NewLine,
    (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "AFM Copilot consolidation completed."
Write-Host "Root:       $Root"
Write-Host "App:        $App"
Write-Host "Data:       $Data"
Write-Host "Workspace:  $Workspace"
Write-Host "Legacy:     $Legacy"
Write-Host "Private JSON/JSONL files rewritten: $privateChanged"
Write-Host "Workspace JSON/JSONL files rewritten: $workspaceChanged"
Write-Host "SQLite scan paths rewritten: $dbChanged"
Write-Host ""
Write-Host "Nothing was deleted. Previous C:\AFM_Copilot contents and old Codex venv are under legacy."
Write-Host "Launcher: $launcher"
