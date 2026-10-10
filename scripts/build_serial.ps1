param([string]$OutputDirectory)
$ErrorActionPreference='Stop'
$repository=Split-Path $PSScriptRoot -Parent
if (-not $OutputDirectory) { $OutputDirectory=Join-Path $repository 'build\serial' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework C# compiler not found' }
& $compiler /nologo /target:exe /out:$(Join-Path $OutputDirectory 'SerialWorker.exe') (Join-Path $repository 'windows\SerialWorker.cs')
if ($LASTEXITCODE -ne 0) { throw 'Serial worker build failed' }
