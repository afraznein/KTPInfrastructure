param(
    [Parameter(Mandatory = $true)]
    [string]$DatasetRoot,

    [Parameter(Mandatory = $true)]
    [string]$MapConfigDirectory,

    [Parameter(Mandatory = $true)]
    [string]$OverviewDirectory,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [string]$PythonCommand = 'python'
)

$ErrorActionPreference = 'Stop'
$builder = Join-Path $PSScriptRoot 'build_spatial_atlas.ps1'
$datasetPath = (Resolve-Path -LiteralPath $DatasetRoot).Path
$configPath = (Resolve-Path -LiteralPath $MapConfigDirectory).Path
$overviewPath = (Resolve-Path -LiteralPath $OverviewDirectory).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
$dataset = Get-Content -LiteralPath (Join-Path $datasetPath 'dataset.json') -Raw | ConvertFrom-Json
$results = [ordered]@{}

New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
foreach ($mapProperty in $dataset.maps.PSObject.Properties) {
    $mapName = $mapProperty.Name
    $mapItem = $mapProperty.Value
    $ordered = @($mapItem.fixtures | Sort-Object { [int]$_.metrics.kills }, { [int]$_.ordinal })
    $target = $ordered[[math]::Floor($ordered.Count / 2)]
    $fixtures = @($mapItem.fixtures | Sort-Object ordinal | ForEach-Object {
        Join-Path $datasetPath $_.files.'hlstatsx-fixture.sql'.path
    })
    $mapOutput = Join-Path $outputPath $mapName
    Write-Output "[$mapName] target=$($target.match_id) kills=$($target.metrics.kills)"
    & $builder `
        -FixtureSql $fixtures `
        -TargetMatch $target.match_id `
        -OverviewBmp (Join-Path $overviewPath "$mapName.bmp") `
        -MapConfig (Join-Path $configPath "$mapName.json") `
        -OutputDirectory $mapOutput `
        -PythonCommand $PythonCommand
    if ($LASTEXITCODE -ne 0) {
        throw "$mapName atlas failed with exit code $LASTEXITCODE"
    }
    $metadata = Get-Content -LiteralPath (Join-Path $mapOutput 'atlas-metadata.json') -Raw | ConvertFrom-Json
    $results[$mapName] = [ordered]@{
        cohort = $mapItem.cohort
        quality_status = $mapItem.quality_status
        target_match_id = $target.match_id
        target_kills = [int]$target.metrics.kills
        images = @($metadata.images).Count
        contact_sheet = "$mapName/99-atlas-contact-sheet.png"
        metadata = "$mapName/atlas-metadata.json"
    }
    $checkpoint = [ordered]@{
        schema_version = 1
        dataset_id = $dataset.dataset_id
        maps = $results
    } | ConvertTo-Json -Depth 8
    Set-Content -LiteralPath (Join-Path $outputPath 'atlas-index.json') -Value $checkpoint -Encoding utf8
}

Write-Output "Generated $($results.Count) competitive-map atlases: $outputPath"
