param(
    [string]$ExePath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ExePath) {
    $ExePath = Join-Path $ProjectRoot "dist\git-lark.exe"
}
$ResolvedExe = (Resolve-Path -LiteralPath $ExePath).Path
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\git-lark"
$InstalledExe = Join-Path $InstallDir "git-lark.exe"

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item -LiteralPath $ResolvedExe -Destination $InstalledExe -Force

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$Entries = @($UserPath -split ";" | Where-Object { $_ })
$AlreadyConfigured = $Entries | Where-Object {
    [string]::Equals($_.TrimEnd("\"), $InstallDir.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)
}
if (-not $AlreadyConfigured) {
    $NewPath = if ($UserPath) { "$UserPath;$InstallDir" } else { $InstallDir }
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
}

Write-Host "Installed: $InstalledExe" -ForegroundColor Green
Write-Host "Open a new terminal, then run: git lark --help" -ForegroundColor Yellow

