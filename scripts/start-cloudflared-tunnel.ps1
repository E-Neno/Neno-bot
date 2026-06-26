$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$Config = Join-Path $env:USERPROFILE ".cloudflared\config.yml"
$OutLog = Join-Path $ProjectRoot "logs\cloudflared-autostart.out.log"
$ErrLog = Join-Path $ProjectRoot "logs\cloudflared-autostart.err.log"

$existing = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*cloudflared*" -and $_.CommandLine -like "*neno-xuanye-work*" }
if ($existing) {
    exit 0
}

if (!(Test-Path -LiteralPath $Cloudflared)) {
    throw "Missing cloudflared executable: $Cloudflared"
}
if (!(Test-Path -LiteralPath $Config)) {
    throw "Missing cloudflared config: $Config"
}

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "logs") | Out-Null
Start-Process -FilePath $Cloudflared `
    -ArgumentList @("--config", $Config, "tunnel", "run", "neno-xuanye-work") `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog
