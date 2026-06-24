# Install debug / release APK to the first connected Android device.
# Usage from anywhere in the repo:
#   powershell -ExecutionPolicy Bypass -File mobile\android\install.ps1 release
#   powershell -ExecutionPolicy Bypass -File mobile\android\install.ps1 debug
# Default variant is debug. release is slower to build but closer to real runtime performance.
param(
    [ValidateSet("debug", "release")]
    [string]$Variant = "debug"
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path $adb)) { Write-Error "adb not found: $adb"; exit 1 }

# Pick the first connected device.
$deviceLine = & $adb devices | Select-String "device$" | Select-Object -First 1
if (-not $deviceLine) { Write-Error "No connected device (adb devices is empty)"; exit 1 }
$device = $deviceLine.ToString().Split("`t")[0]
Write-Host "Device: $device  Variant: $Variant"

if ($Variant -eq "release") {
    & "$root\gradlew.bat" -p $root :app:assembleRelease --console=plain
    $apk = "$root\app\build\outputs\apk\release\app-release.apk"
} else {
    & "$root\gradlew.bat" -p $root :app:assembleDebug --console=plain
    $apk = "$root\app\build\outputs\apk\debug\app-debug.apk"
}
if ($LASTEXITCODE -ne 0) { Write-Error "Build failed"; exit 1 }
if (-not (Test-Path $apk)) { Write-Error "APK not found: $apk"; exit 1 }

# debug and release use the debug keystore, so install -r can preserve app settings.
$out = & $adb -s $device install -r -t $apk 2>&1
$out | Select-Object -Last 2
if ($out -match "INSTALL_FAILED|INCOMPATIBLE") {
    Write-Host "Signature mismatch; reinstalling (local app settings will be lost)..."
    & $adb -s $device uninstall com.neno.app | Out-Null
    & $adb -s $device install -t $apk | Select-Object -Last 1
}
& $adb -s $device shell am start -n com.neno.app/.MainActivity | Out-Null
Write-Host "Installed and launched $Variant build."
