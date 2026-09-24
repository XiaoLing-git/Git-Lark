param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Push-Location $ProjectRoot
try {
    & $Python -m pip install -e ".[build]"
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --name git-lark `
        --paths src `
        src/git_lark/__main__.py
    Write-Host "Built: $ProjectRoot\dist\git-lark.exe" -ForegroundColor Green
}
finally {
    Pop-Location
}

