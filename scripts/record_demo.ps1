# Records a plain-text "terminal recording" of the mock demo (no ffmpeg/asciinema needed).
# Output: docs\demo_recording.txt (timestamped lines). Replay: scripts\replay_demo.ps1
$root = Split-Path $PSScriptRoot -Parent; Set-Location $root
$tmp = Join-Path $env:TEMP "kilnmcp-rec"; New-Item -ItemType Directory -Force $tmp | Out-Null
$out = Join-Path $root "docs\demo_recording.txt"; $t0 = Get-Date
"# kilnmcp demo recording $(Get-Date -Format s) :: python -m kilnmcp.demo --mock-llm (SYNTHETIC DATA)" | Set-Content -Encoding utf8 $out
& .\.venv\Scripts\python.exe -u -m kilnmcp.demo --mock-llm --db "$tmp\k.db" --out $tmp 2>&1 | ForEach-Object {
  $line = "{0,8:N3}`t{1}" -f ((Get-Date) - $t0).TotalSeconds, $_
  Write-Host $_; Add-Content -Encoding utf8 $out $line }
Write-Host "recorded -> $out"
