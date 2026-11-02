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

.PARAMETER Baseline
Also replay a baseline and compare: the shipped defaults plus these overrides,
e.g. @{ max_rise_gap_s = 0 } for the v0.2.0 gate. @{} compares against the
plain defaults. The result gains a Baseline property (score, per-day table, and
how many reference samples got better, worse or stayed the same).

.PARAMETER BaselineRef
Compare against model.py from a git tag or commit, e.g. v0.2.0, instead of the
working tree. 'previous' resolves to the latest release tag. When -Chart is a
directory, the chart is written there as replay-<tag>-vs-current.svg.

.PARAMETER ZoomFrom
Chart: local start of an extra zoom panel (yyyy-MM-ddTHH:mm). Needs -ZoomTo.

.PARAMETER ZoomTo
Chart: local end of the zoom panel.

.PARAMETER Chart
Write a chart to this path (.png or .svg, needs matplotlib): level, optional
zoom, and error vs the reference. Dark mode, colour-blind safe. With -Open,
open it after.

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

.EXAMPLE
# Before/after chart for a model change: the working tree vs the v0.2.0 gate
.\tools\Invoke-TankReplay.ps1 -Baseline @{ max_rise_gap_s = 0 } -ZoomFrom 2026-11-01T18:00 -ZoomTo 2026-11-02T16:30 -Chart compare.png -Open

.EXAMPLE
# The PR chart: the last release vs the working tree, into docs/replay-<tag>-vs-current.svg
.\tools\Invoke-TankReplay.ps1 -BaselineRef previous -ZoomFrom 2026-11-01T18:00 -ZoomTo 2026-11-02T16:30 -Chart docs
#>
[CmdletBinding()]
param(
    [string]$Site = 'cr',
    [string]$From,
    [string]$To,
    [hashtable]$Parameter = @{},
    [hashtable]$Baseline,
    [string]$BaselineRef,
    [string]$ZoomFrom,
    [string]$ZoomTo,
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
if ($PSBoundParameters.ContainsKey('Baseline')) {
    $replayArgs.Add('--compare')
    foreach ($name in $Baseline.Keys) {
        $value = [string]::Format([cultureinfo]::InvariantCulture, '{0}', $Baseline[$name])
        $replayArgs.AddRange([string[]]@('--baseline-param', "${name}=${value}"))
    }
}
if ($BaselineRef) {
    if ($BaselineRef -eq 'previous') {
        $BaselineRef = git -C $repoRoot describe --tags --abbrev=0
        if ($LASTEXITCODE -ne 0 -or -not $BaselineRef) { throw 'No release tag found for -BaselineRef previous.' }
        Write-Verbose "Baseline: latest release tag $BaselineRef"
    }
    $replayArgs.AddRange([string[]]@('--baseline-ref', $BaselineRef))
}
if ($ZoomFrom -and $ZoomTo) { $replayArgs.AddRange([string[]]@('--zoom-from', $ZoomFrom, '--zoom-to', $ZoomTo)) }
if ($Chart) {
    $chartPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Chart)
    if (Test-Path -LiteralPath $chartPath -PathType Container) {
        $chartName = if ($BaselineRef) { "replay-$BaselineRef-vs-current.svg" } else { 'replay-current.svg' }
        $chartPath = Join-Path $chartPath $chartName
    }
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
    Baseline         = if ($summary.baseline) {
        [pscustomobject]@{
            Ref       = $summary.baseline.ref
            Overrides = @($summary.baseline.overrides)
            Score     = $summary.baseline.score
            Days      = @($summary.baseline.days | ForEach-Object { [pscustomobject]@{ Day = $_.day; Samples = $_.samples; Mean = $_.mean; Median = $_.median; P90 = $_.p90; Max = $_.max; Bias = $_.bias } })
            Better    = $summary.baseline.better
            Worse     = $summary.baseline.worse
            Same      = $summary.baseline.same
        }
    }
    Chart            = $summary.chart
    TicksFile        = $summary.ticks_file
}

if ($Open -and $result.Chart) { Invoke-Item $result.Chart }
$result
