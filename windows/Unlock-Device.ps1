param([string]$SealedPath = (Join-Path $PSScriptRoot 'device.sealed.json'), [string]$OutputPath = (Join-Path $PSScriptRoot 'device.json'), [switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
function Open-DeviceConfiguration([string]$Path, [string]$Password) {
    $s = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($s.version -ne 1 -or $s.iterations -ne 200000 -or $s.algorithm -ne 'AES-256-CBC-HMAC-SHA256-PBKDF2-SHA256') { throw 'Unsupported encrypted configuration format.' }
    $salt = [Convert]::FromBase64String($s.salt)
    $iv = [Convert]::FromBase64String($s.iv)
    $cipher = [Convert]::FromBase64String($s.ciphertext)
    $tag = [Convert]::FromBase64String($s.mac)
    if ($salt.Length -ne 32 -or $iv.Length -ne 16 -or $tag.Length -ne 32 -or $cipher.Length -gt 16384) { throw 'Invalid encrypted configuration.' }
    $kdf = [Security.Cryptography.Rfc2898DeriveBytes]::new($Password,$salt,200000,[Security.Cryptography.HashAlgorithmName]::SHA256)
    $keys = $kdf.GetBytes(64)
    $kdf.Dispose()
    $hmac = [Security.Cryptography.HMACSHA256]::new([byte[]]$keys[32..63])
    $authenticated = [byte[]]([Text.Encoding]::UTF8.GetBytes('USB-AI-DEVICE-V1') + $salt + $iv + $cipher)
    $expected = $hmac.ComputeHash($authenticated)
    $hmac.Dispose()
    $difference = 0
    for ($i=0; $i -lt 32; $i++) { $difference = $difference -bor ($expected[$i] -bxor $tag[$i]) }
    if ($difference -ne 0) { [Array]::Clear($keys,0,$keys.Length); throw 'Incorrect unlock password or damaged configuration.' }
    $aes = [Security.Cryptography.Aes]::Create()
    $aes.Key = [byte[]]$keys[0..31]
    $aes.IV = $iv
    $aes.Mode = [Security.Cryptography.CipherMode]::CBC
    $aes.Padding = [Security.Cryptography.PaddingMode]::PKCS7
    $transform = $aes.CreateDecryptor()
    try { $plain = $transform.TransformFinalBlock($cipher,0,$cipher.Length) }
    finally { $transform.Dispose(); $aes.Dispose(); [Array]::Clear($keys,0,$keys.Length) }
    try { return [Text.Encoding]::UTF8.GetString($plain) }
    finally { [Array]::Clear($plain,0,$plain.Length) }
}
if ($MyInvocation.InvocationName -ne '.') {
    Write-Host 'USB AI Bridge - unlock the device configuration' -ForegroundColor Cyan
    Write-Host 'Use the unlock password supplied in the chat, not your Windows or Raspberry Pi password.'
    $secure = Read-Host 'Unlock password' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        $plain = Open-DeviceConfiguration -Path $SealedPath -Password $password
        $cfg = $plain | ConvertFrom-Json
        if ($cfg.device_ip -ne '172.31.240.1' -or -not $cfg.admin_token -or -not $cfg.proxy_password) { throw 'Invalid device configuration.' }
        if (-not $ValidateOnly) {
            if (Test-Path -LiteralPath $OutputPath) {
                $existing=Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
                if ($existing.key_updated_at -and $existing.admin_token -ne $cfg.admin_token) {
                    throw 'This backup has a different management key. Export a fresh encrypted configuration from the panel; the current configuration was preserved.'
                }
            }
            [IO.File]::WriteAllText($OutputPath,$plain,[Text.UTF8Encoding]::new($false))
            $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
            & icacls.exe $OutputPath /inheritance:r /grant:r "*$($identity):(F)" '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Configuration decrypted, but Windows could not restrict its file permissions. Keep it private.' }
        }
        Write-Host 'Device configuration unlocked. You can now run Start-Serial.cmd.' -ForegroundColor Green
    }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr); $password=$null; $plain=$null; $secure.Dispose() }
}
