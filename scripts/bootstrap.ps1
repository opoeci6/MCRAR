<#
.SYNOPSIS
  Creates the MCRAR project-local toolchain inside the repo (.tools/, .cache/, backend/.venv,
  frontend/node_modules). Nothing is installed system-wide. Idempotent.

.DESCRIPTION
  Run:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
  Pinned versions and SHA-256 hashes come from scripts\toolchain.lock.
  Compatible with Windows PowerShell 5.1.

.PARAMETER ToolsOnly
  Only download and verify uv and Node; skip the Python install and the backend/frontend sync.
#>
param([switch]$ToolsOnly)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Tools = Join-Path $Root '.tools'

function Read-Lock([string]$Path) {
    $map = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$') { $map[$Matches[1]] = $Matches[2] }
    }
    return $map
}

function Get-LockValue($Lock, [string]$Key) {
    if (-not $Lock.ContainsKey($Key) -or [string]::IsNullOrWhiteSpace($Lock[$Key])) {
        throw "scripts\toolchain.lock is missing $Key"
    }
    return $Lock[$Key]
}

function Get-Version([string]$Exe, [string[]]$VersionArgs) {
    if (-not (Test-Path -LiteralPath $Exe)) { return $null }
    try { return (& $Exe @VersionArgs 2>$null | Select-Object -First 1) } catch { return $null }
}

function Invoke-Checked([string]$What, [scriptblock]$Block) {
    Write-Host "==> $What"
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$What failed with exit code $LASTEXITCODE" }
}

function Save-Verified([string]$Url, [string]$Dest, [string]$ExpectedSha256) {
    Write-Host "    downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
    $actual = (Get-FileHash -LiteralPath $Dest -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        Remove-Item -LiteralPath $Dest -Force
        throw "SHA-256 mismatch for $Url`n  expected: $ExpectedSha256`n  actual:   $actual"
    }
    Write-Host "    sha256 OK ($actual)"
}

$lock = Read-Lock (Join-Path $PSScriptRoot 'toolchain.lock')
$uvVersion = Get-LockValue $lock 'UV_VERSION'
$uvSha = Get-LockValue $lock 'UV_SHA256'
$nodeVersion = Get-LockValue $lock 'NODE_VERSION'
$nodeSha = Get-LockValue $lock 'NODE_SHA256'
$pythonVersion = Get-LockValue $lock 'PYTHON_VERSION'

# ---- uv ----
$uvDir = Join-Path $Tools 'uv'
$uvExe = Join-Path $uvDir 'uv.exe'
$uvCurrent = Get-Version $uvExe @('--version')
if ($uvCurrent -and ($uvCurrent -match "^uv $([regex]::Escape($uvVersion))( |$)")) {
    Write-Host "==> uv $uvVersion already installed ($uvExe)"
} else {
    Write-Host "==> Installing uv $uvVersion into $uvDir"
    New-Item -ItemType Directory -Force -Path $uvDir | Out-Null
    $zip = Join-Path $uvDir 'uv-x86_64-pc-windows-msvc.zip'
    Save-Verified "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip" $zip $uvSha
    Expand-Archive -LiteralPath $zip -DestinationPath $uvDir -Force
    Remove-Item -LiteralPath $zip -Force
    if (-not (Test-Path -LiteralPath $uvExe)) { throw "uv.exe not found after extraction in $uvDir" }
}

# ---- Node.js ----
$nodeDir = Join-Path $Tools 'node'
$nodeExe = Join-Path $nodeDir 'node.exe'
$nodeCurrent = Get-Version $nodeExe @('--version')
if ($nodeCurrent -eq "v$nodeVersion") {
    Write-Host "==> Node v$nodeVersion already installed ($nodeExe)"
} else {
    Write-Host "==> Installing Node v$nodeVersion into $nodeDir"
    New-Item -ItemType Directory -Force -Path $nodeDir | Out-Null
    $zip = Join-Path $nodeDir "node-v$nodeVersion-win-x64.zip"
    Save-Verified "https://nodejs.org/dist/v$nodeVersion/node-v$nodeVersion-win-x64.zip" $zip $nodeSha
    $stage = Join-Path $nodeDir '_extract'
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force
    $inner = Join-Path $stage "node-v$nodeVersion-win-x64"
    if (-not (Test-Path -LiteralPath $inner)) { throw "Unexpected Node archive layout in $stage" }
    Get-ChildItem -LiteralPath $inner -Force | ForEach-Object {
        $target = Join-Path $nodeDir $_.Name
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
        Move-Item -LiteralPath $_.FullName -Destination $target
    }
    Remove-Item -LiteralPath $stage -Recurse -Force
    Remove-Item -LiteralPath $zip -Force
    if (-not (Test-Path -LiteralPath $nodeExe)) { throw "node.exe not found after extraction in $nodeDir" }
}

if ($ToolsOnly) {
    Write-Host 'Tools are in place (-ToolsOnly: skipped Python install and project sync).'
    exit 0
}

# ---- Load the project-local env (session only), then use it ----
. (Join-Path $PSScriptRoot 'dev-env.ps1') -Quiet

# UV_PYTHON_INSTALL_REGISTRY=0 and UV_PYTHON_BIN_DIR (set by dev-env) stop uv from writing
# to the Windows registry; --no-bin keeps executables out of ~/.local/bin as well.
Invoke-Checked "uv python install $pythonVersion (into .tools\python)" {
    & uv python install $pythonVersion --no-bin --no-registry
}

$backend = Join-Path $Root 'backend'
if (Test-Path -LiteralPath (Join-Path $backend 'pyproject.toml')) {
    Push-Location $backend
    try { Invoke-Checked 'uv sync (backend)' { & uv sync } } finally { Pop-Location }
} else {
    Write-Host '==> backend\pyproject.toml not found; skipping uv sync'
}

$frontend = Join-Path $Root 'frontend'
if (Test-Path -LiteralPath (Join-Path $frontend 'package.json')) {
    Push-Location $frontend
    try {
        # npm.cmd explicitly: avoids npm.ps1 being blocked by the default execution policy.
        if (Test-Path -LiteralPath (Join-Path $frontend 'package-lock.json')) {
            Invoke-Checked 'npm ci (frontend)' { & npm.cmd ci }
        } else {
            Invoke-Checked 'npm install (frontend, first time)' { & npm.cmd install }
        }
    } finally { Pop-Location }
} else {
    Write-Host '==> frontend\package.json not found; skipping npm install'
}

Write-Host ''
Write-Host 'Bootstrap complete. Next: . .\scripts\dev-env.ps1   (or: source scripts/dev-env.sh)'
