param(
  [switch]$PythonOnly,
  [switch]$FrontendOnly
)

$ErrorActionPreference = "Stop"

function Test-PythonModule {
  param([string]$ModuleName)
  $result = python -c "import importlib.util; print('yes' if importlib.util.find_spec('$ModuleName') else 'no')" 2>$null
  return ($result -join "").Trim() -eq "yes"
}

function Invoke-PythonCoverage {
  if (-not (Test-PythonModule "pytest")) {
    Write-Host "Python coverage skipped: install pytest and pytest-cov first." -ForegroundColor Yellow
    return
  }

  Write-Host "Running Python coverage..." -ForegroundColor Cyan
  python -m pytest `
    --cov=chat_server `
    --cov=intelligence `
    --cov=mcp_server `
    --cov=services `
    --cov=streaming `
    --cov=airflow `
    --cov=data_quality_dag `
    --cov-report=term-missing `
    --cov-report=html `
    --cov-report=xml
}

function Invoke-FrontendCoverage {
  $frontendDir = Join-Path $PSScriptRoot "..\\frontend"
  if (-not (Test-Path (Join-Path $frontendDir "node_modules\\vitest"))) {
    Write-Host "Frontend coverage skipped: run 'npm install' in frontend first." -ForegroundColor Yellow
    return
  }

  Write-Host "Running frontend coverage..." -ForegroundColor Cyan
  Push-Location $frontendDir
  try {
    npm run coverage
  } finally {
    Pop-Location
  }
}

if (-not $FrontendOnly) {
  Invoke-PythonCoverage
}

if (-not $PythonOnly) {
  Invoke-FrontendCoverage
}
