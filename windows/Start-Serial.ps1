param([string]$Port, [string]$Workspace, [switch]$PanelOnly)
$ErrorActionPreference='Stop'
$panelProcess=$null
try {
    $device=Join-Path $PSScriptRoot 'device.json'
    $node=Join-Path $PSScriptRoot 'runtime\node.exe'
    if (-not (Test-Path -LiteralPath $device)) { throw 'Run Setup-Device.cmd with your existing Pi management key, or copy your own device.json here first.' }
    if (-not (Test-Path -LiteralPath $node)) { throw 'Copy the runtime folder from your complete v2 package here first.' }
    if (-not $Port) {
        $ports=@(Get-CimInstance Win32_SerialPort | Where-Object { $_.PNPDeviceID -like 'USB\VID_0525&PID_A4A7*' })
        if ($ports.Count -eq 1) { $Port=$ports[0].DeviceID }
        else { [IO.Ports.SerialPort]::GetPortNames() | ForEach-Object { Write-Host $_ }; $Port=Read-Host 'Pi USB AI Serial COM port (for example COM5)' }
    }
    if ($Port -notmatch '^COM[0-9]+$') { throw 'Invalid COM port name' }
    if (-not $PanelOnly -and -not $Workspace) {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog=[Windows.Forms.FolderBrowserDialog]::new()
        $dialog.Description='Choose the folder the AI may read and modify'
        if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { exit 0 }
        $Workspace=$dialog.SelectedPath;$dialog.Dispose()
    }
    $cfg=Get-Content -LiteralPath $device -Raw | ConvertFrom-Json
    $base='http://127.0.0.1:18766'
    # Do not attach to an unrelated listener or leave an invisible background agent.
    $probe=[Net.Sockets.TcpClient]::new()
    try { $probe.Connect('127.0.0.1',18766);throw 'Port 18766 is already occupied. Close the earlier serial launcher first.' }
    catch [Net.Sockets.SocketException] { }
    finally { $probe.Dispose() }
    $panelArgs=@(('"'+(Join-Path $PSScriptRoot 'serial-panel.mjs')+'"'),'--port',$Port,'--device',('"'+$device+'"'))
    if (-not $PanelOnly) { $panelArgs+=@('--workspace',('"'+$Workspace+'"')) }
    $panelProcess=Start-Process -FilePath $node -ArgumentList $panelArgs -WindowStyle Hidden -PassThru
    $ready=$false
    for($i=0;$i -lt 20;$i++) {
        if($panelProcess.HasExited) { throw 'Serial panel exited before startup' }
        try { $health=Invoke-RestMethod -Uri ($base+'/health') -TimeoutSec 1 -Proxy $null; if($health.transport -eq 'serial') { $ready=$true;break } } catch { }
        Start-Sleep -Milliseconds 300
    }
    if (-not $ready) { throw 'Local panel did not start' }
    Start-Process ($base+'/#token='+[Uri]::EscapeDataString($cfg.admin_token))
    Write-Host ('USB serial: '+$Port+' | Local panel: '+$base) -ForegroundColor Cyan
    Write-Host 'Keep this window open. Ctrl+C closes this session. No USB network adapter is used.'
    if($PanelOnly) { Wait-Process -Id $panelProcess.Id }
    else {
        Write-Host 'Files in the selected workspace can be read and changed by submitted tasks.'
        Write-Host 'Terminal commands and deletions follow the selected session approval mode.'
        & $node (Join-Path $PSScriptRoot 'client.mjs') --device $device --workspace $Workspace --base $base
    }
} catch { Write-Host $_.Exception.Message -ForegroundColor Red;Read-Host 'Press Enter to close';exit 1 }
finally { if($panelProcess -and -not $panelProcess.HasExited) { Stop-Process -Id $panelProcess.Id } }
