param([string]$ClientDirectory=$PSScriptRoot)
$ErrorActionPreference='Stop'
$report=[Collections.Generic.List[string]]::new()
function Note([string]$text){$report.Add($text);Write-Host $text}
Note 'USB AI connection check (read-only; no keys or conversation content in report)'
Note ('Time: '+(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Note 'Expected panel URL: http://127.0.0.1:18766/'
try {
 $ports=@(Get-CimInstance Win32_SerialPort)
 foreach($p in $ports){Note ('Serial port: '+$p.DeviceID+' | '+$p.Name+' | status='+$p.Status)}
 if(!$ports.Count){Note 'No serial ports returned by Windows.'}
}catch{Note 'Serial-port inventory unavailable.'}
try {
 $devices=@(Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -like 'USB\VID_0525*' -or $_.Name -match 'Raspberry|USB AI|\(COM[0-9]+\)' })
 foreach($p in $devices){Note ('Device: '+$p.Name+' | status='+$p.Status+' | Windows problem code='+$p.ConfigManagerErrorCode)}
}catch{Note 'Device status unavailable.'}
try {
 $workers=@(Get-Process -Name SerialWorker -ErrorAction SilentlyContinue)
 Note ('Serial workers running: '+$workers.Count)
 if($workers.Count -gt 1){Note 'Multiple workers: check for duplicate USB AI launchers.'}
}catch{Note 'Worker inventory unavailable.'}
foreach($n in @('serial-panel.mjs','key-manager.mjs')){
 $f=Join-Path $ClientDirectory $n
 if(Test-Path -LiteralPath $f){Note ($n+' SHA256: '+(Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash)}else{Note ('Missing '+$n+'; put this tool in the client folder.')}
}
$privateKey=$null
$script:latestSession=$null
try {
 $f=Join-Path $ClientDirectory 'device.json'
 if(Test-Path -LiteralPath $f){$privateKey=(Get-Content -LiteralPath $f -Raw|ConvertFrom-Json).admin_token;Note 'Local device configuration: readable.'}
 else{Note 'Local device configuration: missing.'}
}catch{Note 'Local device configuration: unreadable or invalid JSON.'}
function Probe([string]$route,[int]$timeout=5){
 $req=[Net.HttpWebRequest]::Create('http://127.0.0.1:18766/'+$route)
 $req.Proxy=$null;$req.Timeout=$timeout*1000;$req.ReadWriteTimeout=$timeout*1000
 if($privateKey){$req.Headers['Authorization']='Bearer '+$privateKey}
 $response=$null;$reader=$null;$clock=[Diagnostics.Stopwatch]::StartNew()
 try{
  try{$response=$req.GetResponse()}catch [Net.WebException]{if($_.Exception.Response){$response=$_.Exception.Response}else{Note ($route.Split('?')[0]+' -> no HTTP response ('+$_.Exception.Status+').');return}}
  $reader=[IO.StreamReader]::new($response.GetResponseStream());$text=$reader.ReadToEnd()
  Note ($route.Split('?')[0]+' -> HTTP '+[int]$response.StatusCode+' in '+$clock.ElapsedMilliseconds+' ms; UTF8 bytes='+[Text.Encoding]::UTF8.GetByteCount($text))
  if($clock.ElapsedMilliseconds -gt 20000){Note '  WARNING: slower than the browser 20-second request deadline.'}
  try{$data=$text|ConvertFrom-Json}catch{Note 'Response was not JSON; check whether another application owns port 18766.';return}
  if($route -eq 'api/workbench/sessions'){$script:latestSession=@($data.sessions | Where-Object { !$_.state -or $_.state -eq 'active' } | Select-Object -First 1).id;Note ('  sessions='+@($data.sessions).Count)}
  if($route -eq 'api/workbench/model'){Note ('  provider='+$data.provider+'; configured_ready='+$data.ready)}
  # Print only explicitly allowed diagnostic fields, never general response/config bodies.
  foreach($field in @('ok','transport','connected','busy','recovery','auth_required','code')){
   if($null -ne $data.$field){Note ('  '+$field+'='+[string]$data.$field)}
  }
  if($data.error){$message=[string]$data.error;if($privateKey){$message=$message.Replace($privateKey,'[redacted]')};Note ('  error='+$message.Substring(0,[Math]::Min(400,$message.Length)))}
 }catch{Note ($route.Split('?')[0]+' -> probe failed (no private response recorded).')}
 finally{if($reader){$reader.Dispose()};if($response){$response.Close()};$req.Abort()}
}
Probe 'health'
if($privateKey){Probe 'api/security/status';Probe 'api/transport';Probe 'api/workbench/model' 70;Probe 'api/status' 70;Probe 'api/workbench/sessions' 70;if($script:latestSession -match '^[a-f0-9]{24}$'){Probe ('api/workbench/session?id='+$script:latestSession) 70}}
$privateKey=$null
Note 'Interpretation: no health response = local launcher/listener issue; connected=false = USB/authentication issue.'
Note 'HTTP401 = management key mismatch; KEY_BUSY = handshake in progress; HTTP502/timeout after connected=true = Pi service/USB response issue.'
Note 'A successful model probe confirms a Pi management response. It does not test external AI connectivity.'
$output=Join-Path $PSScriptRoot ('connection-check-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.txt')
[IO.File]::WriteAllLines($output,$report,[Text.UTF8Encoding]::new($true))
Write-Host ('Report saved: '+$output)
