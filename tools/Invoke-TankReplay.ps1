<#
.SYNOPSIS
Replays NEXT (this change, the working tree's model.py) against PREV (the
latest release, the one installed now) over the recorded data in this repo,
and writes the PREV vs NEXT chart to docs/.

.DESCRIPTION
Run with no arguments, it:
  1. for each fixed window in data/<Site>/benchmark.json, replays NEXT (the
     working tree's model.py) and PREV (model.py of the latest release tag,
     e.g. v0.2.0) from empty, ticking every 10 s as Home Assistant does;
  2. correlates both with the pressure sensor in hPa: rank correlation, and
     hour by hour whether the level rises, falls or holds with pressure.
     Pressure is a different physical quantity and is never converted into a
     level, nor ever a model input. The owner's reference-annotations.csv
     spans are a level in % and are checked as one;
  3. writes one chart per window, docs/replay-<from>-to-<to>.svg;
  4. returns one result per window (Correlation, Days, Owner, Baseline with
     the hours NEXT fixed and broke, Window).

The only inputs are the two raw readings: the ultrasonic distance (m) and
the pressure (hPa). Nothing derived is read.

This is part of the engineering process for every model change: run it and
commit the regenerated docs/replay-*.svg with the PR. A window's file name
never changes and its days are fixed, so each file's git history shows how
the model changed over time on the same data.
-NoChart skips the SVG; -NoBaseline replays only the working tree.

.PARAMETER Site
Folder under data/. Default: cr.

.PARAMETER From
First Costa Rica day to load (yyyy-MM-dd). Replaces the benchmark windows.

.PARAMETER To
Last Costa Rica day to load (yyyy-MM-dd). Replaces the benchmark windows.

.PARAMETER AllData
Replay every day in data/<Site> instead of the benchmark windows.

.PARAMETER Parameter
TankParameters overrides for experiments, e.g. @{ full_m = 0.23; floor_m = 2.12 }.
The shipped model.py is not changed.

.PARAMETER Baseline
Also replay a baseline and compare: the shipped defaults plus these overrides,
e.g. @{ max_rise_gap_s = 0 } for the v0.2.0 gate. @{} compares against the
plain defaults. The result gains a Baseline property (score, per-day table, and
how many reference samples got better, worse or stayed the same).

.PARAMETER BaselineRef
PREV: model.py from this git tag or commit. Default 'previous', the latest
release tag. When -Chart is a directory (default docs), the chart is written
there as replay.svg.

.PARAMETER NoBaseline
Replay only the working tree, no comparison.

.PARAMETER NoChart
Do not write a chart.

.PARAMETER ZoomFrom
Chart: local start of an extra zoom panel (yyyy-MM-ddTHH:mm). Needs -ZoomTo.

.PARAMETER ZoomTo
Chart: local end of the zoom panel.

.PARAMETER Chart
Write a chart to this path (.png or .svg, needs matplotlib): level with pressure
on its own hPa axis, optional zoom, and the hours that disagree with pressure. Dark mode, colour-blind safe. With -Open,
open it after.

.PARAMETER TicksPath
Write every published tick (level, volume, flow, lock, reference) to this CSV.

.PARAMETER Python
Python executable. Default: python on PATH.

.EXAMPLE
# The standard run: PREV (latest release) vs NEXT (this change) on every benchmark window,
# writes docs/replay-<from>-to-<to>.svg
.\tools\Invoke-TankReplay.ps1 | Format-Table Window, @{n='PrevDisagree';e={$_.Baseline.Correlation.disagree}}, @{n='NextDisagree';e={$_.Correlation.disagree}}, @{n='Hours';e={$_.Correlation.hours}}

.EXAMPLE
# How the model changed over time on one window
git log -p docs/replay-2026-11-01-to-2026-11-02.svg

.EXAMPLE
.\tools\Invoke-TankReplay.ps1 -From 2026-11-01 -Chart replay.png -Open

.EXAMPLE
# Compare the shipped parameters against a candidate fix
$base = .\tools\Invoke-TankReplay.ps1
$test = .\tools\Invoke-TankReplay.ps1 -Parameter @{ full_m = 0.23 }
$base.Correlation, $test.Correlation

.EXAMPLE
# Before/after chart for a model change: the working tree vs the v0.2.0 gate
.\tools\Invoke-TankReplay.ps1 -Baseline @{ max_rise_gap_s = 0 } -ZoomFrom 2026-11-01T18:00 -ZoomTo 2026-11-02T16:30 -Chart compare.png -Open

#>
[CmdletBinding()]
param(
    [string]$Site = 'cr',
    [string]$From,
    [string]$To,
    [switch]$AllData,
    [hashtable]$Parameter = @{},
    [hashtable]$Baseline,
    [string]$BaselineRef = 'previous',
    [switch]$NoBaseline,
    [string]$ZoomFrom,
    [string]$ZoomTo,
    [string]$Chart = (Join-Path (Split-Path $PSScriptRoot -Parent) 'docs'),
    [switch]$NoChart,
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
# Benchmark windows: with no -From/-To/-AllData, replay each fixed window into its
# own stable chart, docs/replay-<from>-to-<to>.svg, so each file's history is the
# model's history on the same days.
$benchmarkFile = Join-Path $repoRoot (Join-Path 'data' (Join-Path $Site 'benchmark.json'))
if (-not $AllData -and -not $From -and -not $To -and (Test-Path -LiteralPath $benchmarkFile)) {
    $windows = @((Get-Content -LiteralPath $benchmarkFile -Raw | ConvertFrom-Json).windows)
    foreach ($window in $windows) {
        $windowParams = @{} + $PSBoundParameters
        $windowParams['From'] = $window.from
        $windowParams['To'] = $window.to
        if ($Chart -and -not $NoChart -and -not $PSBoundParameters.ContainsKey('Chart')) {
            $windowParams['Chart'] = Join-Path $Chart "replay-$($window.from)-to-$($window.to).svg"
        }
        Write-Verbose "Benchmark window $($window.from) .. $($window.to): $($window.what)"
        $windowResult = & $PSCommandPath @windowParams
        $windowResult | Add-Member -NotePropertyName Window -NotePropertyValue $window.what -PassThru
    }
    return
}
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
# The release tag is the default baseline, unless -Baseline (parameter overrides of
# the working tree) was asked for instead, or -NoBaseline.
$useRef = -not $NoBaseline -and $BaselineRef -and ($PSBoundParameters.ContainsKey('BaselineRef') -or -not $PSBoundParameters.ContainsKey('Baseline'))
if (-not $useRef) { $BaselineRef = $null }
if ($BaselineRef) {
    if ($BaselineRef -eq 'previous') {
        $BaselineRef = git -C $repoRoot describe --tags --abbrev=0
        if ($LASTEXITCODE -ne 0 -or -not $BaselineRef) { throw 'No release tag found for -BaselineRef previous.' }
        Write-Verbose "Baseline: latest release tag $BaselineRef"
    }
    $replayArgs.AddRange([string[]]@('--baseline-ref', $BaselineRef))
}
if ($ZoomFrom -and $ZoomTo) { $replayArgs.AddRange([string[]]@('--zoom-from', $ZoomFrom, '--zoom-to', $ZoomTo)) }
if ($Chart -and -not $NoChart) {
    $chartPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Chart)
    if (-not $PSBoundParameters.ContainsKey('Chart')) { $null = New-Item -ItemType Directory -Force -Path $chartPath }
    if (Test-Path -LiteralPath $chartPath -PathType Container) {
        $chartPath = Join-Path $chartPath $(if ($From -or $To) { "replay-$From-to-$To.svg" } else { 'replay-all.svg' })
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

function ConvertTo-CorrelationDay($day) {
    [pscustomobject]@{
        Day = $day.day; Samples = $day.samples; RankCorrelation = $day.rank_correlation; Hours = $day.hours
        Disagree = $day.disagree; FalseMove = $day.false_move; MissedMove = $day.missed_move; WrongWay = $day.wrong_way
    }
}

$result = [pscustomobject]@{
    PSTypeName       = 'UltrasonicTank.Replay'
    Start            = $summary.start
    End              = $summary.end
    Frames           = $summary.frames
    PressureSamples  = $summary.pressure_samples
    Correlation      = $summary.correlation
    Days             = @($summary.days | ForEach-Object { ConvertTo-CorrelationDay $_ })
    Owner            = $summary.owner
    Inflows          = @($summary.inflows | ForEach-Object { [pscustomobject]@{ Start = $_.start; End = $_.end; PeakLpm = $_.peak_lpm; PressureBeforeHpa = $_.pressure_before_hpa; PressureAfterHpa = $_.pressure_after_hpa } })
    SurfaceLockedPct = $summary.surface_locked_pct
    FinalLevelPct    = $summary.final_level_pct
    Overrides        = @($summary.overrides)
    Parameters       = $summary.parameters
    Files            = @($summary.files)
    Baseline         = if ($summary.baseline) {
        [pscustomobject]@{
            Ref       = $summary.baseline.ref
            Overrides = @($summary.baseline.overrides)
            Correlation = $summary.baseline.correlation
            Days      = @($summary.baseline.days | ForEach-Object { ConvertTo-CorrelationDay $_ })
            Owner     = $summary.baseline.owner
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
