# 一键在手机上切换 debug / release 包。
# 用法（在仓库任意位置）：
#   powershell -ExecutionPolicy Bypass -File mobile\android\install.ps1 release
#   powershell -ExecutionPolicy Bypass -File mobile\android\install.ps1 debug
# 不带参数默认 debug。release 比 debug 慢很多但流畅（真实性能）；debug 快、适合迭代。
param(
    [ValidateSet("debug", "release")]
    [string]$Variant = "debug"
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path $adb)) { Write-Error "找不到 adb：$adb"; exit 1 }

# 自动选第一台已连接设备
$device = (& $adb devices | Select-String "device$" | Select-Object -First 1).ToString().Split("`t")[0]
if (-not $device) { Write-Error "没有已连接的设备（adb devices 为空）"; exit 1 }
Write-Host "设备：$device  变体：$Variant"

if ($Variant -eq "release") {
    & "$root\gradlew.bat" -p $root :app:assembleRelease --console=plain
    $apk = "$root\app\build\outputs\apk\release\app-release.apk"
} else {
    & "$root\gradlew.bat" -p $root :app:assembleDebug --console=plain
    $apk = "$root\app\build\outputs\apk\debug\app-debug.apk"
}
if ($LASTEXITCODE -ne 0) { Write-Error "构建失败"; exit 1 }
if (-not (Test-Path $apk)) { Write-Error "没找到 APK：$apk"; exit 1 }

# debug 和 release 都用 debug keystore 签名 → 同签名，可 install -r 互相覆盖、保留设置。
$out = & $adb -s $device install -r -t $apk 2>&1
$out | Select-Object -Last 2
if ($out -match "INSTALL_FAILED|INCOMPATIBLE") {
    Write-Host "签名不兼容，卸载重装（会丢本地设置）..."
    & $adb -s $device uninstall com.neno.app | Out-Null
    & $adb -s $device install -t $apk | Select-Object -Last 1
}
& $adb -s $device shell am start -n com.neno.app/.MainActivity | Out-Null
Write-Host "已装上 $Variant 包并启动。"
