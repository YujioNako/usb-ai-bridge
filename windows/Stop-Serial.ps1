$ErrorActionPreference='Stop'
$pidFile=Join-Path $PSScriptRoot 'serial-panel.pid'
if(-not (Test-Path -LiteralPath $pidFile)) { Write-Host 'No recorded serial panel process.';exit 0 }
$panelPid=0
if(-not [int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(),[ref]$panelPid)) { throw 'Invalid panel PID file' }
$process=Get-CimInstance Win32_Process -Filter ('ProcessId='+$panelPid)
$expectedScript=[regex]::Escape((Join-Path $PSScriptRoot 'serial-panel.mjs'))
if($process -and $process.Name -eq 'node.exe' -and $process.CommandLine -match $expectedScript) {
    Stop-Process -Id $panelPid
    Write-Host 'Serial panel stopped. Close any remaining Agent terminal window.'
} elseif($process) { throw 'Recorded PID belongs to another process; it was not stopped.' }
Remove-Item -LiteralPath $pidFile
