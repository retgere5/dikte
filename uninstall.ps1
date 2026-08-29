# Dikte uninstaller for Windows. -Purge also removes settings and data.
param(
    [switch]$Purge,
    [switch]$Yes
)
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Say($m)  { Write-Host "  $m" }
function Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Gone($m) { Write-Host "  [.] $m" -ForegroundColor DarkGray }

# Same raw-registry read/write as install.ps1: GetEnvironmentVariable expands
# REG_EXPAND_SZ entries (like the default per-user WindowsApps one) and would
# write them back flattened, permanently undoing what install.ps1 was careful
# not to touch.
function Get-RawUserPath {
    (Get-Item "HKCU:\Environment").GetValue("Path", "", "DoNotExpandEnvironmentNames")
}

function Set-RawUserPath($Value) {
    if (Get-ItemProperty -Path "HKCU:\Environment" -Name Path -ErrorAction SilentlyContinue) {
        Set-ItemProperty -Path "HKCU:\Environment" -Name Path -Value $Value -Type ExpandString
    } else {
        New-ItemProperty -Path "HKCU:\Environment" -Name Path -Value $Value -PropertyType ExpandString | Out-Null
    }
    Add-Type -Namespace Dikte -Name NativeMethods -ErrorAction SilentlyContinue -MemberDefinition @"
        [System.Runtime.InteropServices.DllImport("user32.dll", SetLastError = true, CharSet = System.Runtime.InteropServices.CharSet.Auto)]
        public static extern System.IntPtr SendMessageTimeout(System.IntPtr hWnd, uint Msg, System.UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out System.UIntPtr lpdwResult);
"@
    $result = [System.UIntPtr]::Zero
    [Dikte.NativeMethods]::SendMessageTimeout([System.IntPtr]0xffff, 0x1A, [System.UIntPtr]::Zero, "Environment", 0x2, 5000, [ref]$result) | Out-Null
}

# A per-call -ErrorAction with an honest message, replacing a single blanket
# $ErrorActionPreference = "SilentlyContinue" that used to cover the whole
# script and made every failure invisible, including a failed purge that
# still printed success.
function Remove-IfPresent($Path) {
    if (-not (Test-Path -LiteralPath $Path)) { Gone "Was not there: $Path"; return }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        Ok "Removed $Path"
    } catch {
        Warn "Could not remove $Path`: $($_.Exception.Message)"
    }
}

# Only a shortcut this checkout actually made goes: one of the same name that
# points somewhere else is not ours to delete (mirrors uninstall.sh only
# removing its own $BIN_DIR/dikte symlink).
function Remove-DikteShortcut($Path) {
    if (-not (Test-Path -LiteralPath $Path)) { Gone "Was not there: $Path"; return }
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($Path)
    if (-not $lnk.Arguments.ToLower().Contains($Dir.ToLower())) {
        Warn "$Path does not point at this checkout, leaving it alone"
        return
    }
    try {
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        Ok "Removed $Path"
    } catch {
        Warn "Could not remove $Path`: $($_.Exception.Message)"
    }
}

function Count-Words($n, $singular, $plural) {
    if ($n -eq 1) { "$n $singular" } else { "$n $plural" }
}

function Dir-Size($Path) {
    $bytes = (Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
              Measure-Object -Property Length -Sum).Sum
    if (-not $bytes) { $bytes = 0 }
    if ($bytes -ge 1GB) { "{0:N1} GB" -f ($bytes / 1GB) }
    elseif ($bytes -ge 1MB) { "{0:N1} MB" -f ($bytes / 1MB) }
    elseif ($bytes -ge 1KB) { "{0:N1} KB" -f ($bytes / 1KB) }
    else { "$bytes B" }
}

Write-Host ""
Write-Host "Uninstalling Dikte"
Write-Host "-------------------"

$BinDir = Join-Path $env:LOCALAPPDATA "Programs\Dikte"
$ConfigDir = Join-Path $env:APPDATA "Dikte"
$DataDir = Join-Path $env:LOCALAPPDATA "Dikte"
$ProgramsLnk = Join-Path ([Environment]::GetFolderPath("Programs")) "Dikte.lnk"
$StartupLnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Dikte.lnk"

# 1. The running instance ----------------------------------------------------
# It holds a tray icon and the global shortcuts through RegisterHotKey;
# asking it to quit is tidier than pulling the launchers out from under it,
# and leaves it no longer holding the keys once this script is done.
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    # "quit" is one of dikte.py's idempotent verbs: asking a not-running
    # instance to quit is itself a success (exit 0, {"ok": true, "running":
    # false}), the same as asking a running one (exit 0, {"ok": true}, no
    # "running" key) - so the exit code alone cannot tell the two apart, and
    # --json is read to say the honest thing either way. Only stdout is
    # captured, not stderr: redirecting a native command's stderr under
    # $ErrorActionPreference = "Stop" wraps each line in a terminating
    # NativeCommandError (the same hazard install.ps1's PyQt6 check had).
    $replyText = & python (Join-Path $Dir "dikte.py") quit --json
    if ($LASTEXITCODE -eq 0) {
        $reply = $null
        try { $reply = $replyText | ConvertFrom-Json } catch {}
        if ($reply -and ($reply.PSObject.Properties.Name -contains "running") -and -not $reply.running) {
            Gone "Was not running"
        } else {
            Start-Sleep -Milliseconds 500
            Ok "Stopped the running instance"
        }
    } else {
        Warn "Could not confirm Dikte quit cleanly (exit code $LASTEXITCODE)"
    }
} else {
    Warn "Python not found, so a running instance could not be asked to quit."
}

# 2. Launchers ----------------------------------------------------------------
Remove-IfPresent $BinDir

$UserPath = Get-RawUserPath
$Segments = if ($UserPath) { @($UserPath -split ";") } else { @() }
if ($Segments -contains $BinDir) {
    $Cleaned = ($Segments | Where-Object { $_ -ne "" -and $_ -ne $BinDir }) -join ";"
    Set-RawUserPath $Cleaned
    Ok "Removed from your PATH"
} else {
    Gone "Was not on your PATH: $BinDir"
}

Remove-DikteShortcut $ProgramsLnk
Remove-DikteShortcut $StartupLnk

# 3. Settings and dictations --------------------------------------------------
$DoPurge = $Purge.IsPresent
if ($DoPurge) {
    Write-Host ""
    Warn "-Purge also deletes:"
    $ConfigFile = Join-Path $ConfigDir "config.json"
    if (Test-Path -LiteralPath $ConfigFile) {
        Say "$ConfigFile  (your API keys and every setting)"
    }
    $HistoryFile = Join-Path $DataDir "history.jsonl"
    if (Test-Path -LiteralPath $HistoryFile) {
        $lines = @(Get-Content -LiteralPath $HistoryFile -ErrorAction SilentlyContinue).Count
        Say "$HistoryFile  ($(Count-Words $lines 'dictation' 'dictations'))"
    }
    $MeetingsDir = Join-Path $DataDir "meetings"
    if (Test-Path -LiteralPath $MeetingsDir) {
        $meetings = @(Get-ChildItem -LiteralPath $MeetingsDir -Filter "*.md" -ErrorAction SilentlyContinue).Count
        Say "$MeetingsDir  ($(Count-Words $meetings 'meeting' 'meetings'))"
    }
    $RecordingsDir = Join-Path $DataDir "recordings"
    if (Test-Path -LiteralPath $RecordingsDir) {
        Say "$RecordingsDir  ($(Dir-Size $RecordingsDir) of audio)"
    }
    $ModelsDir = Join-Path $DataDir "models"
    if (Test-Path -LiteralPath $ModelsDir) {
        Say "$ModelsDir  ($(Dir-Size $ModelsDir) of speech and cleanup models)"
    }

    if (-not $Yes) {
        if ([Console]::IsInputRedirected) {
            $DoPurge = $false
            Warn "Not a terminal, so nothing was deleted. Pass -Yes if you meant it."
        } else {
            $confirm = Read-Host "  Type yes to delete them"
            if ($confirm -ne "yes") {
                $DoPurge = $false
                Say "Kept."
            }
        }
    }
}

if ($DoPurge) {
    Remove-IfPresent $ConfigDir
    Remove-IfPresent $DataDir
    Ok "Settings and dictations deleted"
} else {
    Write-Host ""
    Say "Settings kept:     $ConfigDir"
    Say "Dictations kept:   $DataDir"
    Say "Delete them too with:  .\uninstall.ps1 -Purge"
}

Write-Host ""
Ok "Done."
Say "The source directory is untouched: $Dir"
Write-Host ""
