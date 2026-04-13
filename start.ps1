<# AutoForge — 无限自主进化开发框架启动脚本 #>
param(
    [string]$ConfigFile = "autoforge_config.json",
    [switch]$Init,
    [switch]$Loop
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host @"
    ╔═══════════════════════════════════════════════════╗
    ║       AutoForge — 无限自主进化开发框架               ║
    ║       Infinite Autonomous Development             ║
    ╚═══════════════════════════════════════════════════╝
"@ -ForegroundColor Cyan

# Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "ERROR: Python not found in PATH" -ForegroundColor Red
    exit 1
}
Write-Host "Python: $($python.Source)" -ForegroundColor Green

# Check copilot
$copilot = Get-Command copilot -ErrorAction SilentlyContinue
if (-not $copilot) {
    Write-Host "ERROR: Copilot CLI not found in PATH" -ForegroundColor Red
    exit 1
}
Write-Host "Copilot: $($copilot.Source)" -ForegroundColor Green

# Init mode
if ($Init) {
    Write-Host "`nInitializing AutoForge project..." -ForegroundColor Yellow
    python -m autoforge -c $ConfigFile --init
    exit $LASTEXITCODE
}

# Normal run or crash-recovery loop
if ($Loop) {
    Write-Host "`nStarting AutoForge in infinite crash-recovery loop..." -ForegroundColor Yellow
    Write-Host "Press Ctrl+C to stop.`n" -ForegroundColor Gray

    $retryCount = 0
    $maxBackoff = 300  # max 5 minutes between retries

    while ($true) {
        $startTime = Get-Date
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting AutoForge (attempt #$($retryCount + 1))" -ForegroundColor Cyan

        try {
            python -m autoforge -c $ConfigFile
            $exitCode = $LASTEXITCODE
        }
        catch {
            $exitCode = 1
            Write-Host "Exception: $_" -ForegroundColor Red
        }

        $duration = (Get-Date) - $startTime

        if ($exitCode -eq 0) {
            Write-Host "AutoForge exited cleanly." -ForegroundColor Green
            break
        }

        $retryCount++
        # Exponential backoff: 10s, 20s, 40s, 80s, 160s, 300s (max)
        $backoff = [Math]::Min(10 * [Math]::Pow(2, [Math]::Min($retryCount - 1, 5)), $maxBackoff)

        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] AutoForge crashed after $($duration.TotalSeconds.ToString('F0'))s (exit=$exitCode)" -ForegroundColor Red
        Write-Host "Restarting in ${backoff}s... (attempt #$($retryCount + 1))" -ForegroundColor Yellow

        Start-Sleep -Seconds $backoff

        # Reset retry count if last run lasted > 10 minutes (was healthy)
        if ($duration.TotalMinutes -gt 10) {
            $retryCount = 0
        }
    }
}
else {
    # Single run (no crash recovery loop)
    Write-Host "`nStarting AutoForge (single run)..." -ForegroundColor Yellow
    Write-Host "Tip: Use -Loop for crash-recovery mode`n" -ForegroundColor Gray
    python -m autoforge -c $ConfigFile
}
