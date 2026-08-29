# Pull the latest Dikte and put the launchers back, keeping your shortcuts.
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
& git -C $Dir pull --ff-only

# An update can add a dependency or move a file, so the installer runs again.
# It would otherwise register its own defaults over the keys you chose, so
# whatever is presently configured is read back and passed through. On a
# checkout old enough that the verb itself is missing, install.ps1 is called
# without arguments and writes its own defaults instead.
$installArgs = @()
try {
    $current = & python "$Dir\dikte.py" shortcut status --json | ConvertFrom-Json
    if ($current.shortcuts.toggle.configured) {
        $installArgs += "-Shortcut", $current.shortcuts.toggle.configured
    }
    if ($current.shortcuts.cancel.configured) {
        $installArgs += "-CancelShortcut", $current.shortcuts.cancel.configured
    }
} catch {
    # Older checkout without "shortcut status --json" yet: fall through to
    # install.ps1's own defaults.
}
& powershell -ExecutionPolicy Bypass -File (Join-Path $Dir "install.ps1") @installArgs
& python "$Dir\dikte.py" restart | Out-Null
