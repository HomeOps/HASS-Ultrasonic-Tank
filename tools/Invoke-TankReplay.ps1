<#
.SYNOPSIS
Replays the shipped Python model (model.py) over the recorded data in this
repo and returns the score against the reference sensor.

.DESCRIPTION
Runs tools/replay.py, which feeds every raw distance frame in data/<Site>/*.csv
to TankModel from empty, ticking every 10 s as Home Assistant does, and scores
the published level against the hydrostatic reference. The reference is used
for scoring only; it never reaches the model.

Returns one object with the overall score, a Days table (per local day), the
inflow events the model reported, and the parameters used.

.PARAMETER Site
Folder under data/. Default: cr.

.PARAMETER From
First UTC day file to load (yyyy-MM-dd). Default: all.

.PARAMETER To
Last UTC day file to load (yyyy-MM-dd). Default: all.

.PARAMETER Parameter
TankParameters overrides for experiments, e.g. @{ full_m = 0.23; floor_m = 2.12 }.
The shipped model.py is not changed.

.PARAMETER Chart
Write a PNG chart to this path (needs matplotlib). With -Open, open it after.

.PARAMETER TicksPath
Write every published tick (level, volume, flow, lock, reference) to this CSV.

.PARAMETER Python
Python executable. Default: python on PATH.

.EXAMPLE
.\tools\Invoke-TankReplay.ps1

.EXAMPLE
.\tools\Invoke-TankReplay.ps1 -From 2026-11-01 -Chart replay.png -Open

.EXAMPLE
# Compare the shipped parameters against a candidate fix
$base = .\tools\Invoke-TankReplay.ps1
$test = .\tools\Invoke-TankReplay.ps1 -Parameter @{ full_m = 0.23 }
$base.Score, $test.Score
#>
[CmdletBinding()]
param(
    [string]$Site = 'cr',
    [string]$From,
    [string]$To,
    [hashtable]$Parameter = @{},
    [string]$Chart,
    [switch]$Open,
    [string]$TicksPath,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$script = Join-Path $PSScriptRoot 'replay.py'

$pythonExe = Get-Command $Python -CommandType Application -ErrorAction Ignore | Select-Object -First 1
if (-not $pythonExe) { throw "Python not found ('$Python'). Install Python 3.11+ or pass -Python <path>." }

$replayArgs = [System.Collections.Generic.List[string]]::new()
$replayArgs.Add($script)
$replayArgs.AddRange([string[]]@('--site', $Site))
if ($From) { $replayArgs.AddRange([string[]]@('--from', $From)) }
if ($To) { $replayArgs.AddRange([string[]]@('--to', $To)) }
foreach ($name in $Parameter.Keys) {
    $value = [string]::Format([cultureinfo]::InvariantCulture, '{0}', $Parameter[$name])
    $replayArgs.AddRange([string[]]@('--param', "${name}=${value}"))
}
if ($Chart) {
    $chartPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Chart)
    $replayArgs.AddRange([string[]]@('--chart', $chartPath))
}
if ($TicksPath) {
    $ticksFile = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($TicksPath)
    $replayArgs.AddRange([string[]]@('--ticks', $ticksFile))
}

Write-Verbose "Running $($pythonExe.Source) $($replayArgs -join ' ')"
$started = Get-Date
Push-Location $repoRoot
try {
    $output = & $pythonExe.Source @replayArgs
    if ($LASTEXITCODE -ne 0) { throw "replay.py failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
Write-Verbose ("Replay took {0:n1} s" -f ((Get-Date) - $started).TotalSeconds)

$summary = ($output -join "`n") | ConvertFrom-Json

$result = [pscustomobject]@{
    PSTypeName       = 'UltrasonicTank.Replay'
    Start            = $summary.start
    End              = $summary.end
    Frames           = $summary.frames
    ReferenceSamples = $summary.reference_samples
    Score            = $summary.score
    Days             = @($summary.days | ForEach-Object { [pscustomobject]@{ Day = $_.day; Samples = $_.samples; Mean = $_.mean; Median = $_.median; P90 = $_.p90; Max = $_.max; Bias = $_.bias } })
    Inflows          = @($summary.inflows | ForEach-Object { [pscustomobject]@{ Start = $_.start; End = $_.end; PeakLpm = $_.peak_lpm; ReferenceBefore = $_.reference_before; ReferenceAfter = $_.reference_after } })
    SurfaceLockedPct = $summary.surface_locked_pct
    FinalLevelPct    = $summary.final_level_pct
    Overrides        = @($summary.overrides)
    Parameters       = $summary.parameters
    Files            = @($summary.files)
    Chart            = $summary.chart
    TicksFile        = $summary.ticks_file
}

if ($Open -and $result.Chart) { Invoke-Item $result.Chart }
$result
