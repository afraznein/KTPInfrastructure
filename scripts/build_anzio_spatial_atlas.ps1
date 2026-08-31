param(
    [Parameter(Mandatory = $true)]
    [string[]]$FixtureSql,

    [Parameter(Mandatory = $true)]
    [string]$TargetMatch,

    [Parameter(Mandatory = $true)]
    [string]$OverviewBmp,

    [string]$OutputDirectory = 'build/anzio-spatial-atlas',
    [string]$PythonCommand = 'python',
    [string]$MapConfig = '',
    [switch]$KeepAggregatePayload
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$prepare = Join-Path $PSScriptRoot 'prepare_anzio_spatial_atlas.py'
$render = Join-Path $PSScriptRoot 'render_anzio_spatial_atlas.ps1'
$mapConfigPath = if ($MapConfig) {
    (Resolve-Path -LiteralPath $MapConfig).Path
} else {
    Join-Path $repoRoot 'config\analytics\spatial_maps\dod_anzio.json'
}
$output = [System.IO.Path]::GetFullPath($OutputDirectory)
$overview = (Resolve-Path -LiteralPath $OverviewBmp).Path
$fixtureInputs = @($FixtureSql | ForEach-Object { $_ -split '[;,]' } | Where-Object { $_ })
$fixtures = @($fixtureInputs | ForEach-Object { (Resolve-Path -LiteralPath $_).Path })

if ($fixtures.Count -eq 0) { throw 'At least one fixture is required.' }
New-Item -ItemType Directory -Path $output -Force | Out-Null
$payload = Join-Path $output 'atlas-render-data.aggregate.json'

$prepareArgs = @($prepare)
foreach ($fixture in $fixtures) { $prepareArgs += @('--fixture', $fixture) }
$prepareArgs += @('--target-match', $TargetMatch, '--map-config', $mapConfigPath, '--output', $payload)

& $PythonCommand @prepareArgs
if ($LASTEXITCODE -ne 0) { throw "Atlas preparation failed with exit code $LASTEXITCODE." }

& $render -AtlasJson $payload -OverviewBmp $overview -OutputDirectory $output -MapConfig $mapConfigPath
if ($LASTEXITCODE -ne 0) { throw "Atlas rendering failed with exit code $LASTEXITCODE." }

if (-not $KeepAggregatePayload) {
    # This is a generated, aggregate-only renderer payload, not source data.
    Remove-Item -LiteralPath $payload -Force
}

Write-Output "Anzio atlas complete: $output"
