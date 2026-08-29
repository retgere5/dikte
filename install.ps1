# Dikte installer for Windows: dependency check, launchers, shortcuts.
param(
    [string]$Shortcut = "Ctrl+Space",
    [string]$CancelShortcut = "Ctrl+Alt+Space"
)
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Say($m)  { Write-Host "  $m" }
function Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }

Write-Host ""
Write-Host "Installing Dikte"
Write-Host "----------------"

# 1. Dependencies -----------------------------------------------------------
$py = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $py) { Warn "Python not found. Install 3.11+ from python.org or winget."; exit 1 }
$version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
$parts = $version.Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
    Warn "Python $version is too old; Dikte needs 3.11 or newer."; exit 1
}
Ok "Python $version"

& python -c "import PyQt6.QtWidgets" 2>$null
if ($LASTEXITCODE -ne 0) {
    Say "Installing PyQt6..."
    & python -m pip install --quiet PyQt6
    if ($LASTEXITCODE -ne 0) { Warn "pip could not install PyQt6"; exit 1 }
}
Ok "PyQt6 present"

if ($null -eq (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Warn "ffmpeg not found. Recording needs it:  winget install Gyan.FFmpeg"
} else { Ok "ffmpeg present" }

# 2. The dikte command ------------------------------------------------------
$BinDir = Join-Path $env:LOCALAPPDATA "Programs\Dikte"
New-Item -ItemType Directory -Force $BinDir | Out-Null
$pythonw = Join-Path (Split-Path $py.Source) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $py.Source }
@"
@echo off
"$($py.Source)" "$Dir\dikte.py" %*
"@ | Out-File -Encoding ascii (Join-Path $BinDir "dikte.cmd")
Ok "Command installed: $BinDir\dikte.cmd"

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$UserPath;$BinDir", "User")
    Ok "Added to your PATH (new terminals will see it)"
}

# 3. Start menu and autostart ----------------------------------------------
$Shell = New-Object -ComObject WScript.Shell
$Programs = [Environment]::GetFolderPath("Programs")
$Startup = [Environment]::GetFolderPath("Startup")
foreach ($where in @($Programs, $Startup)) {
    $lnk = $Shell.CreateShortcut((Join-Path $where "Dikte.lnk"))
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "`"$Dir\dikte.py`""
    $lnk.WorkingDirectory = $Dir
    $lnk.Description = "Voice dictation: record, transcribe, clean up, paste"
    $lnk.Save()
}
Ok "Start menu entry and autostart added"

# 4. Global shortcuts -------------------------------------------------------
# Dikte holds these itself through RegisterHotKey while it runs; installing
# only writes the combination into the settings, where the listener reads it.
if ($Shortcut -eq $CancelShortcut) {
    Warn "Both arguments are $Shortcut, so the discard key was left out."
    $CancelShortcut = ""
}
# $ErrorActionPreference = "Stop" does not catch a non-zero exit code from an
# external executable (only from cmdlets), so each call is checked against
# $LASTEXITCODE the same way the pip-install step above is. A conflict (the
# combination is already used elsewhere, and --force was not passed) is not
# fatal: the app still runs, just without that shortcut until it is set from
# Settings or the command printed below.
& python "$Dir\dikte.py" shortcut install toggle --combo $Shortcut | Out-Null
if ($LASTEXITCODE -eq 0) {
    Ok "Start and stop: $Shortcut"
} else {
    Warn "Could not register $Shortcut. Run 'dikte shortcut install toggle --combo `"$Shortcut`" --force' or pick a different combination."
}
if ($CancelShortcut) {
    & python "$Dir\dikte.py" shortcut install cancel --combo $CancelShortcut | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Ok "Discard the recording: $CancelShortcut"
    } else {
        Warn "Could not register $CancelShortcut. Run 'dikte shortcut install cancel --combo `"$CancelShortcut`" --force' or pick a different combination."
    }
}

Write-Host ""
Ok "Done. Start it with:  dikte"
Say "The settings window opens on first run: download a speech model, or add"
Say "an OpenAI or OpenRouter key instead."
Write-Host ""
