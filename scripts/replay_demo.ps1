# Replays docs\demo_recording.txt with original timing.
$root = Split-Path $PSScriptRoot -Parent; $prev = 0.0
Get-Content (Join-Path $root "docs\demo_recording.txt") | Select-Object -Skip 1 | ForEach-Object {
  $t, $txt = $_ -split "`t", 2; $t = [double]$t
  Start-Sleep -Milliseconds ([int][math]::Max(0, ($t - $prev) * 1000)); $prev = $t; Write-Host $txt }
