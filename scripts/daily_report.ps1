# Runs the daily research report and refreshes the dashboard.
# Intended for Windows Task Scheduler (see docs/WINDOWS_SETUP.md).
# Research / paper-trading only: this script never places orders.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"

& $py -m agent_trading report
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m agent_trading dashboard
exit $LASTEXITCODE
