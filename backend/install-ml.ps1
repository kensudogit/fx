# Optional ML packages (TensorFlow ~390MB, PyTorch ~203MB)
# Usage:  .\install-ml.ps1
#         .\install-ml.ps1 -Package tensorflow
#         .\install-ml.ps1 -Package torch

param(
    [ValidateSet("all", "tensorflow", "torch")]
    [string]$Package = "all",
    [int]$MaxAttempts = 5
)

$ErrorActionPreference = "Stop"
$Backend = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPip = Join-Path $Backend ".venv\Scripts\pip.exe"

if (-not (Test-Path $VenvPip)) {
    Write-Host "ERROR: .venv not found. Run install.bat first." -ForegroundColor Red
    exit 1
}

$Packages = switch ($Package) {
    "tensorflow" { @("tensorflow==2.18.0") }
    "torch"      { @("torch==2.5.1") }
    default      { @("tensorflow==2.18.0", "torch==2.5.1") }
}

$WheelsDir = Join-Path $Backend "wheels"
New-Item -ItemType Directory -Force -Path $WheelsDir | Out-Null

function Install-WithRetry {
    param([string]$Spec)

    for ($i = 1; $i -le $MaxAttempts; $i++) {
        Write-Host ""
        Write-Host "=== $Spec (attempt $i / $MaxAttempts) ===" -ForegroundColor Cyan

        # Step 1: download wheel to local folder (retry-friendly)
        & $VenvPip download $Spec `
            -d $WheelsDir `
            --retries 10 `
            --timeout 600 `
            --no-cache-dir
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Download failed. Retrying in 10s..." -ForegroundColor Yellow
            Start-Sleep -Seconds 10
            continue
        }

        # Step 2: install from local wheels (no network needed)
        & $VenvPip install --no-index --find-links $WheelsDir $Spec
        if ($LASTEXITCODE -eq 0) {
            Write-Host "OK: $Spec installed" -ForegroundColor Green
            return $true
        }

        Write-Host "Install failed. Retrying in 10s..." -ForegroundColor Yellow
        Start-Sleep -Seconds 10
    }

    Write-Host "FAILED: $Spec (after $MaxAttempts attempts)" -ForegroundColor Red
    return $false
}

$Failed = @()
foreach ($spec in $Packages) {
    if (-not (Install-WithRetry -Spec $spec)) {
        $Failed += $spec
    }
}

Write-Host ""
if ($Failed.Count -eq 0) {
    Write-Host "=== All ML packages installed ===" -ForegroundColor Green
    exit 0
}

Write-Host "=== Partial install ===" -ForegroundColor Yellow
Write-Host "Failed: $($Failed -join ', ')"
Write-Host "Core backend works without these. Re-run:  .\install-ml.ps1"
exit 1
