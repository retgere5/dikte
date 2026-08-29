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

# Reads and writes the user's PATH the way regedit would: as the raw,
# unexpanded string. [Environment]::GetEnvironmentVariable("Path", "User")
# expands REG_EXPAND_SZ entries like %USERPROFILE%\...\WindowsApps before
# handing them back, and SetEnvironmentVariable then writes the expanded text
# back as REG_SZ - permanently flattening any such entry (which is how the
# per-user WindowsApps folder, and with it a "python" alias some machines
# rely on, ships by default). Reading and writing the registry value directly
# with -Type ExpandString keeps every entry exactly as it was.
function Get-RawUserPath {
    (Get-Item "HKCU:\Environment").GetValue("Path", "", "DoNotExpandEnvironmentNames")
}

function Set-RawUserPath($Value) {
    if (Get-ItemProperty -Path "HKCU:\Environment" -Name Path -ErrorAction SilentlyContinue) {
        Set-ItemProperty -Path "HKCU:\Environment" -Name Path -Value $Value -Type ExpandString
    } else {
        New-ItemProperty -Path "HKCU:\Environment" -Name Path -Value $Value -PropertyType ExpandString | Out-Null
    }
    # Broadcasts WM_SETTINGCHANGE so windows already open (Explorer, other
    # shells) notice without a logoff; new processes read the registry fresh
    # regardless and would see it anyway.
    Add-Type -Namespace Dikte -Name NativeMethods -ErrorAction SilentlyContinue -MemberDefinition @"
        [System.Runtime.InteropServices.DllImport("user32.dll", SetLastError = true, CharSet = System.Runtime.InteropServices.CharSet.Auto)]
        public static extern System.IntPtr SendMessageTimeout(System.IntPtr hWnd, uint Msg, System.UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out System.UIntPtr lpdwResult);
"@
    $result = [System.UIntPtr]::Zero
    [Dikte.NativeMethods]::SendMessageTimeout([System.IntPtr]0xffff, 0x1A, [System.UIntPtr]::Zero, "Environment", 0x2, 5000, [ref]$result) | Out-Null
}

Write-Host ""
Write-Host "Installing Dikte"
Write-Host "----------------"

# 0. Elevation --------------------------------------------------------------
# Everything below lands in this account's own profile (LOCALAPPDATA, HKCU,
# the Start menu). Run elevated and all of that resolves to the
# Administrator profile instead - every step still prints [ok], and the
# install is invisible to the person who asked for it.
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Warn "Run this as yourself, not as administrator - Dikte installs into your own profile."
    exit 1
}

# 1. Dependencies -----------------------------------------------------------
$py = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $py) { Warn "Python not found. Install 3.11+ from python.org or winget."; exit 1 }
$version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
# Get-Command also matches the Windows Store app-execution alias, which ships
# enabled with no Python behind it: it prints nothing and $version comes back
# empty (or something with no dot in it), which would otherwise reach
# [int]$parts[0] and throw a raw type-conversion error instead of the
# friendly message written for exactly this case.
if (-not $version -or $version -notmatch "^\d+\.\d+$") {
    Warn "Python not found. Install 3.11+ from python.org or winget."; exit 1
}
$parts = $version.Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
    Warn "Python $version is too old; Dikte needs 3.11 or newer."; exit 1
}
Ok "Python $version"

# Not "2>$null": redirecting a native command's stderr wraps each line in a
# NativeCommandError, which under $ErrorActionPreference = "Stop" is
# terminating and aborts the whole installer - precisely when PyQt6 is
# missing and python writes an ImportError traceback to stderr, which is the
# fresh-install path this script exists for. $LASTEXITCODE alone is enough.
& python -c "import PyQt6.QtWidgets"
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
# cmd.exe reads a batch file in the OEM codepage, not ASCII: "ascii" would
# turn every non-ASCII character in $py.Source or $Dir into "?", so a
# Turkish profile like C:\Users\Sule produces a shim that points nowhere
# while this script still prints [ok].
@"
@echo off
"$($py.Source)" "$Dir\dikte.py" %*
"@ | Out-File -Encoding oem (Join-Path $BinDir "dikte.cmd")

# Smoke-run the shim once before trusting it: "shortcut status --json" is a
# real, cheap, side-effect-free verb that needs no running instance and opens
# no window, so a non-zero exit here means the path above got mangled (or
# something else about the shim is broken) rather than that the shim works.
& $BinDir\dikte.cmd shortcut status --json | Out-Null
if ($LASTEXITCODE -ne 0) {
    Warn "The installed command did not run (exit code $LASTEXITCODE). Check for non-ASCII characters in the install path."
} else {
    Ok "Command installed: $BinDir\dikte.cmd"
}

$UserPath = Get-RawUserPath
# ($UserPath -split ";") -contains $BinDir is an exact match on one segment,
# unlike "-notlike ""*$BinDir*""": the wildcard test breaks on a username
# containing [ or ], and wrongly matches a longer sibling path too.
$Segments = if ($UserPath) { @($UserPath -split ";") } else { @() }
if (-not ($Segments -contains $BinDir)) {
    # Built from the non-empty segments only: "$UserPath;$BinDir" on an empty
    # PATH produces a leading ";", an empty element that Windows resolves as
    # the current directory - recreating the cwd-hijack this port is meant to
    # close elsewhere.
    $NewSegments = @($Segments | Where-Object { $_ -ne "" }) + $BinDir
    Set-RawUserPath ($NewSegments -join ";")
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
