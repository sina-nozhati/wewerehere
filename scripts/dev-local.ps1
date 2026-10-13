# Local dev: FastAPI on http://127.0.0.1:5173
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not $env:ADMIN_PASSWORD) {
  $env:ADMIN_PASSWORD = "test-local"
  Write-Host "ADMIN_PASSWORD not set; using test-local"
}
$env:WW_DISABLE_MIGRATE = "1"

Write-Host "Installing backend Python dependencies ..."
python -m pip install -r backend/requirements.txt
Write-Host "Ticket PNG: uses Chrome/Edge headless when Cairo is missing (same as browser preview)"

Write-Host "Starting uvicorn on http://127.0.0.1:5173 ..."
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 5173
