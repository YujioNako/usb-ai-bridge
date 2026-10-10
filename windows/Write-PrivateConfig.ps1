param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
$taskTarget=[IO.Path]::GetFullPath($ConfigPath)
$taskTemp=Join-Path ([IO.Path]::GetDirectoryName($taskTarget)) ('.key-'+[Guid]::NewGuid().ToString('N')+'.tmp')
try {
    $taskJson=[Console]::In.ReadToEnd()
    if($taskJson.Length -gt 32768){throw 'Configuration too large'}
    $null=$taskJson | ConvertFrom-Json
    $taskAcl=[IO.File]::GetAccessControl($taskTarget)
    [IO.File]::WriteAllText($taskTemp,'')
    [IO.File]::SetAccessControl($taskTemp,$taskAcl)
    $taskBytes=[Text.UTF8Encoding]::new($false).GetBytes($taskJson)
    $taskStream=[IO.File]::Open($taskTemp,[IO.FileMode]::Truncate,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try{$taskStream.Write($taskBytes,0,$taskBytes.Length);$taskStream.Flush($true)}finally{$taskStream.Dispose()}
    [IO.File]::Replace($taskTemp,$taskTarget,[NullString]::Value)
} finally {
    if(Test-Path -LiteralPath $taskTemp){Remove-Item -LiteralPath $taskTemp}
    $taskJson=$null;$taskBytes=$null
}
