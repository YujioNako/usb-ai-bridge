param([string]$OutputPath=(Join-Path $PSScriptRoot 'device.json'))
$ErrorActionPreference='Stop'
function Save-USBConfiguration([Security.SecureString]$ManagementKey,[string]$Destination) {
 $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($ManagementKey)
 $created=$false
 try {
  $key=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
  if($key -notmatch '^[!-~]{16,128}$') { throw 'Management key must be 16-128 ASCII characters without spaces.' }
  if(Test-Path -LiteralPath $Destination) { throw 'device.json already exists; it was not overwritten.' }
  $cfg=@{device_ip='172.31.240.1';admin_token=$key;proxy_password='not-used-by-usb-serial'}
  # Legacy fields are retained for encrypted export compatibility; no USB network connection is created.
  $stream=[IO.File]::Open($Destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  $stream.Dispose();$created=$true
  $identity=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  & icacls.exe $Destination /inheritance:r /grant:r "*$($identity):(F)" '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' | Out-Null
  if($LASTEXITCODE -ne 0) { throw 'Cannot restrict configuration permissions.' }
  [IO.File]::WriteAllText($Destination,($cfg | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
 } catch { if($created -and (Test-Path -LiteralPath $Destination)) {Remove-Item -LiteralPath $Destination};throw }
 finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr);$key=$null;$cfg=$null }
}
if($MyInvocation.InvocationName -ne '.') {
 if(Test-Path -LiteralPath $OutputPath) { Write-Host 'Configuration already exists. Run Start-Serial.cmd; existing settings were preserved.';exit 0 }
 Write-Host 'Enter your EXISTING Pi management key (the same key used by the web panel).'
 Write-Host 'This is not your ChatGPT password. The key is saved locally and is not changed on Pi.'
 $secure=Read-Host 'Pi management key' -AsSecureString
 try { Save-USBConfiguration -ManagementKey $secure -Destination $OutputPath }
 finally { $secure.Dispose() }
 Write-Host 'Configuration saved. Run Start-Serial.cmd and select your workspace.' -ForegroundColor Green
}
