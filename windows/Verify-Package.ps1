$ErrorActionPreference='Stop'
$manifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'package-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$count=0
foreach($entry in $manifest.files) {
 if($entry.path -match '(^/|\\|(^|/)\.\.(/|$)|:)') { throw 'Unsafe manifest path' }
 $file=Join-Path $PSScriptRoot $entry.path
 if(-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw ('Missing file: '+$entry.path) }
 if((Get-Item -LiteralPath $file).Length -ne $entry.bytes -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw ('Checksum mismatch: '+$entry.path) }
 $count++
}
Write-Host ('PASS: '+$count+' package files verified. Run Setup-Device.cmd, then Start-Serial.cmd.') -ForegroundColor Green
