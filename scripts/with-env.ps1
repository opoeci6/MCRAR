<#
  Run ONE command with the MCRAR project-local dev env loaded (for shells that keep no state).
  Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\with-env.ps1 <cmd> [args...]
  Deliberately has no param block, so every argument (including -flags) goes to the command.
#>
if ($args.Count -eq 0) {
    [Console]::Error.WriteLine('usage: scripts\with-env.ps1 <cmd> [args...]')
    exit 2
}
. (Join-Path $PSScriptRoot 'dev-env.ps1') -Quiet
$mcrarCmd = [string]$args[0]
$mcrarRest = @()
if ($args.Count -gt 1) { $mcrarRest = $args[1..($args.Count - 1)] }
& $mcrarCmd @mcrarRest
exit $LASTEXITCODE
