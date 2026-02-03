<#
.SYNOPSIS
    Starts the Zerg Rush backend and frontend servers locally.

.DESCRIPTION
    This script sets up the Python virtual environment, installs dependencies,
    starts the FastAPI backend server using uvicorn, and also starts the
    frontend Vite development server.

.PARAMETER Port
    The port to run the backend server on. Defaults to 8000.

.PARAMETER FrontendPort
    The port to run the frontend server on. Defaults to 3000.

.PARAMETER Hostname
    The host to bind to. Defaults to 127.0.0.1.

.PARAMETER NoReload
    Disable auto-reload for the backend.

.PARAMETER NoFrontend
    Skip starting the frontend server.

.EXAMPLE
    .\start-server.ps1
    Starts backend on http://127.0.0.1:8000 and frontend on http://127.0.0.1:3000.

.EXAMPLE
    .\start-server.ps1 -Port 8080 -FrontendPort 3001
    Starts backend on port 8080 and frontend on port 3001.

.EXAMPLE
    .\start-server.ps1 -NoFrontend
    Starts only the backend server.
#>

param(
    [int]$Port = 8000,
    [int]$FrontendPort = 3000,
    [string]$Hostname = "127.0.0.1",
    [switch]$NoReload,
    [switch]$NoFrontend
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

# Main execution
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Zerg Rush Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$backendDir = Join-Path $ProjectRoot "backend"
$venvDir = Join-Path $backendDir "venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirementsFile = Join-Path $backendDir "requirements.txt"
$envFile = Join-Path $backendDir ".env"
$envExampleFile = Join-Path $backendDir ".env.example"

$frontendDir = Join-Path $ProjectRoot "frontend"
$nodeModulesDir = Join-Path $frontendDir "node_modules"

# Check if .env exists
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExampleFile) {
        Write-Status "Creating .env file from .env.example..."
        Copy-Item $envExampleFile $envFile
        Write-Warning "Please edit backend/.env with your settings before running in production"
    }
    else {
        Write-Failure "No .env or .env.example file found in backend/"
        exit 1
    }
}

# Database container settings
$DbContainerName = "zergrush-db"
$DbPort = 5432
$DbPassword = "postgres"
$DbName = "zergrush"

# Check if Docker is available
$dockerAvailable = $null -ne (Get-Command docker -ErrorAction SilentlyContinue)
if (-not $dockerAvailable) {
    Write-Warning "Docker is not installed or not in PATH"
    Write-Warning "Please ensure PostgreSQL is running manually on localhost:$DbPort"
}
else {
    # Check if container exists
    $containerExists = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $DbContainerName }

    if ($containerExists) {
        # Check if container is running
        $containerRunning = docker ps --format "{{.Names}}" | Where-Object { $_ -eq $DbContainerName }

        if (-not $containerRunning) {
            Write-Status "Starting existing PostgreSQL container..."
            docker start $DbContainerName | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Failure "Failed to start PostgreSQL container"
                exit 1
            }
            Write-Success "PostgreSQL container started"
        }
        else {
            Write-Success "PostgreSQL container is already running"
        }
    }
    else {
        Write-Status "Creating PostgreSQL container..."
        docker run -d `
            --name $DbContainerName `
            -e POSTGRES_PASSWORD=$DbPassword `
            -e POSTGRES_DB=$DbName `
            -p "${DbPort}:5432" `
            postgres:15 | Out-Null

        if ($LASTEXITCODE -ne 0) {
            Write-Failure "Failed to create PostgreSQL container"
            exit 1
        }
        Write-Success "PostgreSQL container created"
    }

    # Wait for PostgreSQL to be ready
    Write-Status "Waiting for PostgreSQL to be ready..."
    $maxAttempts = 30
    $attempt = 0
    $ready = $false

    while (-not $ready -and $attempt -lt $maxAttempts) {
        $attempt++
        $result = docker exec $DbContainerName pg_isready -U postgres 2>&1
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
        }
        else {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $ready) {
        Write-Failure "PostgreSQL did not become ready in time"
        exit 1
    }
    Write-Success "PostgreSQL is ready"

    # Ensure the database exists
    $dbExists = docker exec $DbContainerName psql -U postgres -lqt 2>&1 | Select-String -Pattern "\b$DbName\b"
    if (-not $dbExists) {
        Write-Status "Creating database '$DbName'..."
        docker exec $DbContainerName psql -U postgres -c "CREATE DATABASE $DbName;" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Failure "Failed to create database"
            exit 1
        }
        Write-Success "Database '$DbName' created"
    }
}

# Check if venv exists
if (-not (Test-Path $venvPython)) {
    Write-Status "Creating Python virtual environment..."
    Push-Location $backendDir
    try {
        python -m venv venv
        if ($LASTEXITCODE -ne 0) {
            Write-Failure "Failed to create virtual environment"
            exit 1
        }
        Write-Success "Virtual environment created"
    }
    finally {
        Pop-Location
    }
}

# Check if dependencies are installed (check for uvicorn as indicator)
$uvicornInstalled = & $venvPython -c "import uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Status "Installing dependencies..."
    $venvPip = Join-Path $venvDir "Scripts\pip.exe"
    & $venvPip install -r $requirementsFile
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "Failed to install dependencies"
        exit 1
    }
    Write-Success "Dependencies installed"
}

# Frontend setup
$frontendJob = $null
if (-not $NoFrontend) {
    # Check if npm is available
    $npmAvailable = $null -ne (Get-Command npm -ErrorAction SilentlyContinue)
    if (-not $npmAvailable) {
        Write-Warning "npm is not installed or not in PATH"
        Write-Warning "Skipping frontend startup. Install Node.js to enable frontend."
    }
    else {
        # Check if node_modules exists
        if (-not (Test-Path $nodeModulesDir)) {
            Write-Status "Installing frontend dependencies..."
            Push-Location $frontendDir
            try {
                npm install
                if ($LASTEXITCODE -ne 0) {
                    Write-Failure "Failed to install frontend dependencies"
                    exit 1
                }
                Write-Success "Frontend dependencies installed"
            }
            finally {
                Pop-Location
            }
        }

        # Start frontend dev server as a background job
        Write-Status "Starting frontend dev server on http://${Hostname}:${FrontendPort}"
        $frontendJob = Start-Job -ScriptBlock {
            param($dir, $port)
            Set-Location $dir
            npm run dev -- --port $port
        } -ArgumentList $frontendDir, $FrontendPort
    }
}

# Build uvicorn command
$uvicornArgs = @(
    "-m", "uvicorn",
    "app.main:app",
    "--host", $Hostname,
    "--port", $Port
)

if (-not $NoReload) {
    $uvicornArgs += "--reload"
}

# Start the server
Write-Host ""
Write-Status "Starting backend server on http://${Hostname}:${Port}"
Write-Status "API docs available at http://${Hostname}:${Port}/docs"
if ($frontendJob) {
    Write-Status "Frontend running on http://${Hostname}:${FrontendPort}"
}
Write-Host ""

Push-Location $backendDir
try {
    & $venvPython $uvicornArgs
}
finally {
    Pop-Location
    # Clean up frontend job when backend exits
    if ($frontendJob) {
        Write-Status "Stopping frontend server..."
        Stop-Job -Job $frontendJob -ErrorAction SilentlyContinue
        Remove-Job -Job $frontendJob -ErrorAction SilentlyContinue
    }
}
