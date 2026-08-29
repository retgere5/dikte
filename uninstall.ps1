# Dikte uninstaller for Windows. --purge also removes settings and data.
param([switch]$Purge)
$ErrorActionPreference = "SilentlyContinue"

$BinDir = Join-Path $env:LOCALAPPDATA "Programs\Dikte"
Remove-Item -Recurse -Force $BinDir
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$Cleaned = ($UserPath.Split(';') | Where-Object { $_ -ne $BinDir }) -join ';'
[Environment]::SetEnvironmentVariable("Path", $Cleaned, "User")

Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "Dikte.lnk")
Remove-Item (Join-Path ([Environment]::GetFolderPath("Startup")) "Dikte.lnk")

if ($Purge) {
    Remove-Item -Recurse -Force (Join-Path $env:APPDATA "Dikte")
    Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA "Dikte")
    Write-Host "Removed Dikte with its settings and data."
} else {
    Write-Host "Removed Dikte. Settings and dictations were left alone (-Purge removes them)."
}
