<#
.SYNOPSIS
  Loads the MCRAR project-local dev environment into the CURRENT PowerShell session.

.DESCRIPTION
  Dot-source it:   . .\scripts\dev-env.ps1
  Sets only process-level environment variables and prepends .tools\* to PATH for this
  session. It never uses setx, never writes to the registry and never edits a profile.
  Keep the variable list in sync with scripts/dev-env.sh (a backend test enforces it).
#>
param([switch]$Quiet)

$McrarRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

$env:MCRAR_HOME = $McrarRoot

# uv: binary, managed Pythons, caches, tools. Nothing is registered system-wide.
$env:UV_INSTALL_DIR = Join-Path $McrarRoot '.tools\uv'
$env:UV_NO_MODIFY_PATH = '1'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $McrarRoot '.tools\python'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
$env:UV_PYTHON_BIN_DIR = Join-Path $McrarRoot '.tools\python-bin'
$env:UV_PYTHON_INSTALL_REGISTRY = '0'
$env:UV_PYTHON_INSTALL_BIN = '0'
$env:UV_CACHE_DIR = Join-Path $McrarRoot '.cache\uv'
$env:UV_TOOL_DIR = Join-Path $McrarRoot '.tools\uv-tools'
$env:UV_TOOL_BIN_DIR = Join-Path $McrarRoot '.tools\tool-bin'

# npm: cache and (accidental) global prefix stay local.
$env:npm_config_cache = Join-Path $McrarRoot '.cache\npm'
$env:npm_config_prefix = Join-Path $McrarRoot '.tools\npm-global'
$env:npm_config_update_notifier = 'false'

# ML and tooling caches.
$env:HF_HOME = Join-Path $McrarRoot '.cache\huggingface'
$env:TORCH_HOME = Join-Path $McrarRoot '.cache\torch'
$env:PYTORCH_KERNEL_CACHE_PATH = Join-Path $McrarRoot '.cache\torch\kernels'
$env:TORCHINDUCTOR_CACHE_DIR = Join-Path $McrarRoot '.cache\torchinductor'
$env:NUMBA_CACHE_DIR = Join-Path $McrarRoot '.cache\numba'
$env:MPLCONFIGDIR = Join-Path $McrarRoot '.cache\matplotlib'
$env:XDG_CACHE_HOME = Join-Path $McrarRoot '.cache'

# Never read the per-user site-packages.
$env:PYTHONNOUSERSITE = '1'

# Prepend project tools to PATH (once; session only).
$mcrarPathDirs = @(
    (Join-Path $McrarRoot '.tools\uv'),
    (Join-Path $McrarRoot '.tools\node'),
    $env:UV_PYTHON_BIN_DIR
)
$mcrarKept = @($env:PATH -split ';' | Where-Object { $_ -and ($mcrarPathDirs -notcontains $_) })
$env:PATH = (($mcrarPathDirs + $mcrarKept) -join ';')

if (-not $Quiet) {
    Write-Host "MCRAR dev env loaded (session only): home=$McrarRoot; uv, node and python are project-local (.tools\)."
}
