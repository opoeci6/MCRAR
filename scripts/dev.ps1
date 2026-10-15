<#
.SYNOPSIS
  Runs the MCRAR backend (uvicorn, port 8000) and frontend (Vite) with the project-local tools.
  Ctrl+C in the frontend stops everything; the backend is stopped on exit.

.DESCRIPTION
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev.ps1
#>
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'dev-env.ps1')

$backendProc = $null
try {
    $backendDir = Join-Path $Root 'backend'
    $uvExe = (Get-Command uv -CommandType Application).Source
    Write-Host 'Starting backend on http://127.0.0.1:8000 ...'
    $backendProc = Start-Process -FilePath $uvExe -WorkingDirectory $backendDir -NoNewWindow -PassThru `
        -ArgumentList @('run', 'uvicorn', '--factory', 'mcrar.api.app:create_app', '--host', '127.0.0.1', '--port', '8000', '--reload')

    Write-Host 'Starting frontend (Vite) ...'
    Push-Location (Join-Path $Root 'frontend')
    try {
        # npm.cmd explicitly: avoids npm.ps1 being blocked by the default execution policy.
        & npm.cmd run dev
    } finally {
        Pop-Location
    }
} finally {
    if ($backendProc -and -not $backendProc.HasExited) {
        Write-Host 'Stopping backend ...'
        # /T also stops uvicorn's reloader and worker child processes.
        & taskkill.exe /PID $backendProc.Id /T /F | Out-Null
    }
}
