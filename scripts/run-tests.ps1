<#
.SYNOPSIS
    Runs all tests for the Zerg Rush project.

.DESCRIPTION
    This script sets up the appropriate virtual environments and runs tests
    for all project components (backend, frontend when available).

.PARAMETER Backend
    Run only backend tests.

.PARAMETER Frontend
    Run only frontend tests.

.PARAMETER Coverage
    Generate coverage report for backend tests.

.PARAMETER Quiet
    Show minimal test output.

.EXAMPLE
    .\run-tests.ps1
    Runs all tests.

.EXAMPLE
    .\run-tests.ps1 -Backend -Coverage
    Runs backend tests with coverage report.
#>

param(
    [switch]$Backend,
    [switch]$Frontend,
    [switch]$Coverage,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# Colors for output
function Write-Status($message) {
    Write-Host ":: " -ForegroundColor Blue -NoNewline
    Write-Host $message
}

function Write-Success($message) {
    Write-Host "[OK] " -ForegroundColor Green -NoNewline
    Write-Host $message
}

function Write-Failure($message) {
    Write-Host "[FAIL] " -ForegroundColor Red -NoNewline
    Write-Host $message
}

function Write-Warning($message) {
    Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline
    Write-Host $message
}

# Track overall results
$script:TestResults = @{
    Backend  = $null
    Frontend = $null
}

function Test-Backend {
    Write-Status "Running backend tests..."

    $backendDir = Join-Path $ProjectRoot "backend"
    $venvDir = Join-Path $backendDir "venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    $requirementsFile = Join-Path $backendDir "requirements.txt"

    # Check if venv exists
    if (-not (Test-Path $venvPython)) {
        Write-Status "Creating Python virtual environment..."
        Push-Location $backendDir
        try {
            python -m venv venv
            if ($LASTEXITCODE -ne 0) {
                Write-Failure "Failed to create virtual environment"
                return $false
            }
        }
        finally {
            Pop-Location
        }
    }

    # Check if requirements are installed (check for pytest as indicator)
    $pytestInstalled = & $venvPython -c "import pytest" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Installing dependencies..."
        $venvPip = Join-Path $venvDir "Scripts\pip.exe"
        & $venvPip install -r $requirementsFile
        if ($LASTEXITCODE -ne 0) {
            Write-Failure "Failed to install dependencies"
            return $false
        }
    }

    # Build pytest command
    $pytestArgs = @()

    if ($Coverage) {
        $pytestArgs += "--cov=app"
        $pytestArgs += "--cov-report=term-missing"
        $pytestArgs += "--cov-report=html:coverage_html"
    }

    if ($Quiet) {
        $pytestArgs += "-q"
    }
    else {
        $pytestArgs += "-v"
    }

    # Run tests
    Write-Status "Executing pytest..."
    Push-Location $backendDir
    try {
        $venvPytest = Join-Path $venvDir "Scripts\pytest.exe"
        if ($pytestArgs.Count -gt 0) {
            & $venvPytest $pytestArgs
        }
        else {
            & $venvPytest
        }
        $testResult = $LASTEXITCODE -eq 0

        if ($testResult) {
            Write-Success "Backend tests passed"
        }
        else {
            Write-Failure "Backend tests failed"
        }

        return $testResult
    }
    finally {
        Pop-Location
    }
}

function Test-Frontend {
    Write-Status "Running frontend tests..."

    $frontendDir = Join-Path $ProjectRoot "frontend"
    $packageJson = Join-Path $frontendDir "package.json"

    # Check if package.json has a test script
    $package = Get-Content $packageJson | ConvertFrom-Json
    if (-not $package.scripts.test) {
        Write-Warning "Frontend tests not configured (no 'test' script in package.json)"
        return $null  # Skip, not a failure
    }

    # Check if node_modules exists
    $nodeModules = Join-Path $frontendDir "node_modules"
    if (-not (Test-Path $nodeModules)) {
        Write-Status "Installing frontend dependencies..."
        Push-Location $frontendDir
        try {
            npm install
            if ($LASTEXITCODE -ne 0) {
                Write-Failure "Failed to install frontend dependencies"
                return $false
            }
        }
        finally {
            Pop-Location
        }
    }

    # Run tests
    Push-Location $frontendDir
    try {
        npm test
        $testResult = $LASTEXITCODE -eq 0

        if ($testResult) {
            Write-Success "Frontend tests passed"
        }
        else {
            Write-Failure "Frontend tests failed"
        }

        return $testResult
    }
    finally {
        Pop-Location
    }
}

# Main execution
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Zerg Rush Test Runner" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Determine which tests to run
$runBackend = $Backend -or (-not $Backend -and -not $Frontend)
$runFrontend = $Frontend -or (-not $Backend -and -not $Frontend)

# Run tests
if ($runBackend) {
    $script:TestResults.Backend = Test-Backend
    Write-Host ""
}

if ($runFrontend) {
    $script:TestResults.Frontend = Test-Frontend
    Write-Host ""
}

# Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$exitCode = 0

if ($runBackend) {
    if ($script:TestResults.Backend -eq $true) {
        Write-Success "Backend: PASSED"
    }
    elseif ($script:TestResults.Backend -eq $false) {
        Write-Failure "Backend: FAILED"
        $exitCode = 1
    }
    else {
        Write-Warning "Backend: SKIPPED"
    }
}

if ($runFrontend) {
    if ($script:TestResults.Frontend -eq $true) {
        Write-Success "Frontend: PASSED"
    }
    elseif ($script:TestResults.Frontend -eq $false) {
        Write-Failure "Frontend: FAILED"
        $exitCode = 1
    }
    else {
        Write-Warning "Frontend: SKIPPED"
    }
}

Write-Host ""
exit $exitCode
