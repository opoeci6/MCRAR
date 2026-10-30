<#
.SYNOPSIS
  Builds the Windows portable preview: dist\MCRAR-<version>-preview-win64.zip (own Python 3.11,
  CPU-only PyTorch, the built frontend, the tag heads and a MCRAR.cmd launcher).

.DESCRIPTION
  Run:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-preview.ps1
  Needs the project toolchain from scripts\bootstrap.ps1 (uv, Node, the managed Python) and
  internet access (PyPI and download.pytorch.org). Nothing is installed system-wide: the stage is
  build\preview\MCRAR-<version>-preview, the uv cache is .cache\uv, the zip goes to dist\.
  Compatible with Windows PowerShell 5.1.

.PARAMETER Dev
  Stage from the working tree (tracked and untracked files that are not ignored) instead of
  `git archive HEAD`, allow a dirty tree and name the zip MCRAR-<version>-preview-dev-win64.zip.

.PARAMETER FrontendDist
  Copy this existing frontend build (relative paths are resolved from the repo root) instead of
  running `npm run build`.
#>
param(
    [switch]$Dev,
    [string]$FrontendDist = ''
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'dev-env.ps1') -Quiet

$timer = [Diagnostics.Stopwatch]::StartNew()

function Invoke-Checked([string]$What, [scriptblock]$Block) {
    Write-Host ("==> {0}  [{1:n0}s]" -f $What, $timer.Elapsed.TotalSeconds)
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$What failed with exit code $LASTEXITCODE" }
}

function Remove-Tree([string]$Path) {
    # rmdir /s is far more reliable than Remove-Item -Recurse on big trees in Windows PowerShell 5.1.
    for ($try = 1; (Test-Path -LiteralPath $Path) -and $try -le 3; $try++) {
        & cmd.exe /d /c rmdir /s /q ('"' + $Path + '"')
        if (Test-Path -LiteralPath $Path) { Start-Sleep -Seconds 1 }
    }
    if (Test-Path -LiteralPath $Path) { throw "cannot delete $Path" }
}

# Writes a text file with ASCII bytes and CRLF endings (cmd.exe and Notepad want CRLF).
function Copy-AsCrlf([string]$From, [string]$To) {
    $text = [IO.File]::ReadAllText($From)
    $crlf = $text -replace "`r?`n", ([string][char]13 + [char]10)
    foreach ($ch in $crlf.ToCharArray()) {
        if ([int]$ch -gt 127) { throw "$From contains a non-ASCII character; it must be plain ASCII" }
    }
    [IO.File]::WriteAllText($To, $crlf, (New-Object Text.ASCIIEncoding))
}

# ---- version, names ----
$pyproject = Get-Content -LiteralPath (Join-Path $Root 'backend\pyproject.toml') -Raw
$m = [regex]::Match($pyproject, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $m.Success) { throw 'cannot read the version from backend\pyproject.toml' }
$Version = $m.Groups[1].Value
$FolderName = "MCRAR-$Version-preview"
$ZipName = if ($Dev) { "MCRAR-$Version-preview-dev-win64.zip" } else { "MCRAR-$Version-preview-win64.zip" }

$BuildDir = Join-Path $Root 'build\preview'
$Stage = Join-Path $BuildDir $FolderName
$Tmp = Join-Path $Root 'build\preview-tmp'
$DistDir = Join-Path $Root 'dist'
$ZipPath = Join-Path $DistDir $ZipName
$StagePython = Join-Path $Stage 'python\python.exe'

# Paths that go into the app folder from the repository.
$SourcePaths = @('LICENSE', 'NOTICE.md', 'models/registry.json', 'models/heads', 'packaging/windows')

# The VC++ runtime pieces torch, scikit-learn and the Python launcher need on a PC without the
# Visual C++ redistributable (python-build-standalone already ships the two vcruntime files).
$VcRuntime = @(
    'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'concrt140.dll', 'vcomp140.dll',
    'vcruntime140.dll', 'vcruntime140_1.dll'
)

Write-Host "Building $ZipName (version $Version, $(if ($Dev) { 'working tree, dev' } else { 'git HEAD' }))"

# ---- 1. source ----
if (-not $Dev) {
    $dirty = @(& git -C $Root status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw 'git status failed' }
    if ($dirty.Count -gt 0) {
        throw ("the working tree has uncommitted changes; commit or stash them, or use -Dev to build from the working tree:`n  " + ($dirty -join "`n  "))
    }
}

# ---- 2. stage ----
Remove-Tree $Stage
Remove-Tree $Tmp
New-Item -ItemType Directory -Force -Path $Stage, $Tmp, $DistDir | Out-Null

if ($Dev) {
    Invoke-Checked 'stage files from the working tree' {
        $listed = & git -C $Root -c core.quotepath=off ls-files -co --exclude-standard -- @SourcePaths
        if ($LASTEXITCODE -ne 0) { return }
        foreach ($rel in $listed) {
            $from = Join-Path $Root $rel
            if (-not (Test-Path -LiteralPath $from -PathType Leaf)) { continue }   # deleted, not committed yet
            $to = Join-Path $Stage $rel
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $to) | Out-Null
            Copy-Item -LiteralPath $from -Destination $to
        }
    }
} else {
    Invoke-Checked 'stage files from git archive HEAD' {
        $archive = Join-Path $Tmp 'source.zip'
        & git -C $Root archive --format=zip -o $archive HEAD @SourcePaths
        if ($LASTEXITCODE -ne 0) { return }
        Expand-Archive -LiteralPath $archive -DestinationPath $Stage -Force
        Remove-Item -LiteralPath $archive -Force
    }
}
foreach ($required in 'LICENSE', 'NOTICE.md', 'models\registry.json', 'packaging\windows\MCRAR.cmd', 'packaging\windows\README.txt') {
    if (-not (Test-Path -LiteralPath (Join-Path $Stage $required))) { throw "$required is not in the staged source" }
}
if (@(Get-ChildItem -LiteralPath (Join-Path $Stage 'models\heads') -Filter '*.npz').Count -eq 0) {
    throw 'models\heads has no .npz files in the staged source'
}
Copy-AsCrlf (Join-Path $Stage 'packaging\windows\MCRAR.cmd') (Join-Path $Stage 'MCRAR.cmd')
Copy-AsCrlf (Join-Path $Stage 'packaging\windows\README.txt') (Join-Path $Stage 'README.txt')
Remove-Tree (Join-Path $Stage 'packaging')

# ---- 3. frontend ----
$stageDist = Join-Path $Stage 'frontend\dist'
if ($FrontendDist) {
    $source = if ([IO.Path]::IsPathRooted($FrontendDist)) { $FrontendDist } else { Join-Path $Root $FrontendDist }
    if (-not (Test-Path -LiteralPath (Join-Path $source 'index.html'))) { throw "$source has no index.html" }
    Write-Host "==> copy the frontend build from $source"
    New-Item -ItemType Directory -Force -Path $stageDist | Out-Null
    Copy-Item -Path (Join-Path $source '*') -Destination $stageDist -Recurse -Force
} else {
    # The working tree equals HEAD here (clean check) or is what -Dev asked for.
    Invoke-Checked 'build the frontend (npm run build)' {
        & npm.cmd --prefix (Join-Path $Root 'frontend') run build -- --outDir $stageDist --emptyOutDir
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $stageDist 'index.html'))) { throw 'frontend\dist\index.html is missing from the stage' }

# ---- 4. python ----
$pythonRoot = Join-Path $Root '.tools\python'
$base = @(Get-ChildItem -LiteralPath $pythonRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^cpython-3\.11\.\d+-windows-x86_64-none$' } |
    Sort-Object { [version]($_.Name -replace '^cpython-(\d+\.\d+\.\d+)-.*$', '$1') } -Descending)
if ($base.Count -eq 0) { throw "no managed Python 3.11 in $pythonRoot (run scripts\bootstrap.ps1)" }
Write-Host "==> copy $($base[0].Name) to python\"
Copy-Item -LiteralPath $base[0].FullName -Destination (Join-Path $Stage 'python') -Recurse
Remove-Item -LiteralPath (Join-Path $Stage 'python\Lib\EXTERNALLY-MANAGED') -Force -ErrorAction SilentlyContinue
if (-not (Test-Path -LiteralPath $StagePython)) { throw "$StagePython is missing" }

# ---- 5. packages ----
$lockText = Get-Content -LiteralPath (Join-Path $Root 'backend\uv.lock') -Raw
$cpu = @()
foreach ($name in 'torch', 'torchaudio', 'torchvision') {
    $lm = [regex]::Match($lockText, "(?m)^name = `"$name`"\r?\nversion = `"([0-9.]+)\+cu130`"")
    if (-not $lm.Success) { throw "cannot find $name (+cu130) in backend\uv.lock" }
    $cpu += "$name==$($lm.Groups[1].Value)+cpu"
}
Write-Host "    CPU wheels: $($cpu -join ', ')"

$requirements = Join-Path $Tmp 'requirements.txt'
Invoke-Checked 'uv export (locked dependencies, hashes kept, torch left out)' {
    & uv export --directory (Join-Path $Root 'backend') --frozen --no-dev --extra ml --no-emit-project `
        --no-emit-package torch --no-emit-package torchaudio --no-emit-package torchvision -o $requirements | Out-Null
}
# The export lists every transitive dependency, so --no-deps; with hashes uv then checks each wheel.
Invoke-Checked 'install the locked dependencies' {
    & uv pip install --python $StagePython --link-mode copy --compile-bytecode --no-deps -r $requirements
}
Invoke-Checked 'install CPU-only PyTorch' {
    & uv pip install --python $StagePython --link-mode copy --compile-bytecode --no-deps `
        --index-url https://download.pytorch.org/whl/cpu @cpu
}
Invoke-Checked 'build the mcrar wheel' {
    & uv build --wheel --directory (Join-Path $Root 'backend') -o (Join-Path $Tmp 'wheel')
}
$wheel = @(Get-ChildItem -LiteralPath (Join-Path $Tmp 'wheel') -Filter 'mcrar-*.whl')
if ($wheel.Count -ne 1) { throw "expected one mcrar wheel in $Tmp\wheel, found $($wheel.Count)" }
Invoke-Checked 'install the mcrar wheel' {
    & uv pip install --python $StagePython --link-mode copy --compile-bytecode --no-deps $wheel[0].FullName
}
Invoke-Checked 'uv pip check' {
    & uv pip check --python $StagePython
}

# ---- 6. VC++ runtime ----
$pythonDir = Join-Path $Stage 'python'
$system32 = Join-Path $env:SystemRoot 'System32'
foreach ($dll in $VcRuntime) {
    if (Test-Path -LiteralPath (Join-Path $pythonDir $dll)) { continue }
    $from = Join-Path $system32 $dll
    if (Test-Path -LiteralPath $from) {
        Copy-Item -LiteralPath $from -Destination $pythonDir
        Write-Host "    copied $dll from System32"
    } else {
        Write-Warning "$dll is not next to python.exe and not in System32; a PC without the VC++ runtime may fail to start"
    }
}

# ---- 7. cleanup ----
# The base Python ships an empty Scripts\; what the installs put there (entry-point launchers,
# the numba script) embeds the build machine's interpreter path and is not used by the app.
$scripts = Join-Path $pythonDir 'Scripts'
if (Test-Path -LiteralPath $scripts) {
    Get-ChildItem -LiteralPath $scripts -Force | Remove-Item -Recurse -Force
}
# The wheel's install record names the local build folder.
Get-ChildItem -Path (Join-Path $pythonDir 'Lib\site-packages\mcrar-*.dist-info\direct_url.json') -ErrorAction SilentlyContinue |
    Remove-Item -Force

# ---- 8. guards ----
function Test-Stage {
    $problems = New-Object Collections.Generic.List[string]
    $stageLen = $Stage.Length + 1
    foreach ($top in '.secrets', 'data', '.cache', '.venv', 'node_modules') {
        if (Test-Path -LiteralPath (Join-Path $Stage $top)) { $problems.Add("top-level $top must not be shipped") }
    }
    if (Test-Path -LiteralPath (Join-Path $Stage 'config\settings.toml')) { $problems.Add('config\settings.toml must not be shipped') }
    foreach ($entry in [IO.Directory]::EnumerateFileSystemEntries($Stage)) {
        $leaf = Split-Path -Leaf $entry
        if ($leaf -notin 'MCRAR.cmd', 'README.txt', 'LICENSE', 'NOTICE.md', 'python', 'frontend', 'models') {
            $problems.Add("unexpected top-level entry $leaf")
        }
    }
    foreach ($dir in [IO.Directory]::EnumerateDirectories($Stage, '*', [IO.SearchOption]::AllDirectories)) {
        $leaf = Split-Path -Leaf $dir
        if ($leaf -in '.secrets', '.venv', 'node_modules', '.cache') { $problems.Add("folder $($dir.Substring($stageLen))") }
    }
    $longest = ''
    foreach ($file in [IO.Directory]::EnumerateFiles($Stage, '*', [IO.SearchOption]::AllDirectories)) {
        $rel = $file.Substring($stageLen)
        if ($file -like '*.db') { $problems.Add("database file $rel") }
        if ($rel.Length -gt $longest.Length) { $longest = $rel }
        if ($rel -like 'models\*' -and $rel -notlike 'models\heads\*' -and $rel -ne 'models\registry.json') {
            $problems.Add("unexpected file under models: $rel")
        }
    }
    Write-Host "    longest path: $($longest.Length) characters ($longest)"
    if ($longest.Length -gt 200) { $problems.Add("path longer than 200 characters: $longest") }
    if ($problems.Count -gt 0) { throw ("stage guard failed:`n  " + ($problems -join "`n  ")) }
}
Write-Host "==> check the stage  [$('{0:n0}' -f $timer.Elapsed.TotalSeconds)s]"
Test-Stage

# ---- 9. self-test ----
# A clean environment (nothing from the dev env, no PYTHON* or HF_* variables) plus exactly the
# variables MCRAR.cmd sets, read from the staged launcher so the two cannot drift apart.
function Invoke-CleanPython([string[]]$PyArgs) {
    $saved = @{}
    foreach ($item in Get-ChildItem Env:) { $saved[$item.Name] = $item.Value }
    $keep = 'SystemRoot', 'SystemDrive', 'windir', 'ComSpec', 'PATHEXT', 'TEMP', 'TMP',
        'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'ProgramData', 'ProgramFiles', 'NUMBER_OF_PROCESSORS',
        'PROCESSOR_ARCHITECTURE', 'OS'
    $previousPreference = $ErrorActionPreference
    try {
        foreach ($name in $saved.Keys) {
            if ($keep -notcontains $name) { Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue }
        }
        $env:PATH = (Join-Path $env:SystemRoot 'System32') + ';' + $env:SystemRoot
        foreach ($line in [IO.File]::ReadAllLines((Join-Path $Stage 'MCRAR.cmd'))) {
            $sm = [regex]::Match($line, '^set "([A-Za-z0-9_]+)=(.*)"$')
            if ($sm.Success) { Set-Item -LiteralPath ("Env:" + $sm.Groups[1].Value) -Value $sm.Groups[2].Value.Replace('%APP%', $Stage) }
        }
        $ErrorActionPreference = 'Continue'   # native stderr must not abort the script
        Push-Location $Stage
        try {
            $output = & $StagePython -I @PyArgs 2>&1 | ForEach-Object { "$_" } | Out-String
            $code = $LASTEXITCODE
        } finally { Pop-Location }
    } finally {
        $ErrorActionPreference = $previousPreference
        foreach ($item in Get-ChildItem Env:) { Remove-Item -LiteralPath ("Env:" + $item.Name) -ErrorAction SilentlyContinue }
        foreach ($name in $saved.Keys) { Set-Item -LiteralPath "Env:$name" -Value $saved[$name] }
    }
    return [pscustomobject]@{ Code = $code; Output = $output.TrimEnd() }
}

$selftest = Join-Path $PSScriptRoot 'preview_selftest.py'
foreach ($check in @(
        @{ What = 'python -m mcrar --help'; PyArgs = @('-m', 'mcrar', '--help') },
        @{ What = 'imports and package data'; PyArgs = @($selftest) })) {
    Write-Host "==> self-test: $($check.What)  [$('{0:n0}' -f $timer.Elapsed.TotalSeconds)s]"
    $result = Invoke-CleanPython $check.PyArgs
    $lines = @($result.Output -split "`r?`n" | Where-Object { $_.Trim() })
    $shown = if ($check.What -like '*--help') { $lines | Select-Object -First 2 } else { $lines }
    foreach ($l in $shown) { Write-Host "    $l" }
    if ($result.Code -ne 0) { throw "self-test '$($check.What)' failed with exit code $($result.Code)" }
}
# The runs may have created runtime folders; the zip must not carry them.
foreach ($runtime in 'data', 'config', '.cache', '.secrets') { Remove-Tree (Join-Path $Stage $runtime) }
Test-Stage

# ---- 10. zip ----
$projectPython = Join-Path $base[0].FullName 'python.exe'
Invoke-Checked "zip to dist\$ZipName" {
    & $projectPython -I (Join-Path $PSScriptRoot 'make_preview_zip.py') $BuildDir $FolderName $ZipPath
}
Remove-Tree $Tmp

$bytes = 0L
$count = 0
foreach ($file in [IO.Directory]::EnumerateFiles($Stage, '*', [IO.SearchOption]::AllDirectories)) {
    $bytes += ([IO.FileInfo]$file).Length
    $count++
}
Write-Host ''
Write-Host ("Done in {0:n0}s: {1}" -f $timer.Elapsed.TotalSeconds, $ZipPath)
Write-Host ("  files:    {0:n0}" -f $count)
Write-Host ("  unpacked: {0:n0} MB" -f ($bytes / 1MB))
Write-Host ("  zip:      {0:n0} MB" -f ((Get-Item -LiteralPath $ZipPath).Length / 1MB))
