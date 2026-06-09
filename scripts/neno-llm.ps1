<#
  neno-llm.ps1 - toggle the world LLM and restart the backend.

  Usage:
    powershell -ExecutionPolicy Bypass -File scripts\neno-llm.ps1 on       # LLM thinking (~RMB 0.6/day)
    powershell -ExecutionPolicy Bypass -File scripts\neno-llm.ps1 off      # free mock (she still lives), $0
    powershell -ExecutionPolicy Bypass -File scripts\neno-llm.ps1 status    # show state, no restart

  Notes: edits .env LLM/PLANNER flags then restarts uvicorn (flags are read at startup).
         world_loop stays on, so she keeps living; off = free mock path.
  ASCII-only on purpose: PowerShell 5.1 reads .ps1 as the system codepage, so
  non-ASCII text in this file would break parsing.
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet('on', 'off', 'status')]
  [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
$venvPy  = 'C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe'
$port    = 8000

function Get-EnvVal([string]$key) {
  $line = Select-String -Path $envFile -Pattern "^\s*$key\s*=" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($line) { return ($line.Line -split '=', 2)[1].Trim() }
  return $null
}

function Set-EnvVal([string]$key, [string]$val) {
  $found = $false
  $lines = Get-Content $envFile -Encoding UTF8   # read as UTF-8 so non-ASCII comments are not corrupted
  $out = foreach ($l in $lines) {
    if ($l -match "^\s*$key\s*=") { $found = $true; "$key=$val" } else { $l }
  }
  if (-not $found) { $out = @($out) + "$key=$val" }
  $enc = New-Object System.Text.UTF8Encoding($false)   # no BOM, keep dotenv happy
  [System.IO.File]::WriteAllLines($envFile, $out, $enc)
}

function Get-BackendPid {
  $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($c) { return ($c.OwningProcess | Select-Object -First 1) }
  return $null
}

function Restart-Backend {
  $cur = Get-BackendPid
  if ($cur) { Stop-Process -Id $cur -Force; Start-Sleep -Milliseconds 700 }
  $log = Join-Path $root 'tmp\uvicorn_boot.log'
  Start-Process -FilePath $venvPy `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', "$port" `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err"
  Start-Sleep -Seconds 8
  return (Get-BackendPid)
}

function Show-Status {
  $llm  = Get-EnvVal 'CONSCIOUSNESS_WORLD_LLM_ENABLED'
  $loop = Get-EnvVal 'CONSCIOUSNESS_WORLD_LOOP_ENABLED'
  $plan = Get-EnvVal 'CONSCIOUSNESS_WORLD_PLANNER_ENABLED'
  $bpid = Get-BackendPid
  if ($bpid) { $state = "running (pid $bpid)" } else { $state = "not running" }
  if ($llm -eq '1') { $mode = "LLM thinking (~RMB 0.6/day)" } else { $mode = "free mock, `$0 (she still lives)" }
  Write-Host ""
  Write-Host "  backend:   $state"
  Write-Host "  world loop: LOOP=$loop"
  Write-Host "  llm:       LLM=$llm  PLANNER=$plan  ->  $mode"
  Write-Host ""
}

switch ($Action) {
  'on' {
    Set-EnvVal 'CONSCIOUSNESS_WORLD_LLM_ENABLED' '1'
    Set-EnvVal 'CONSCIOUSNESS_WORLD_PLANNER_ENABLED' '1'
    Write-Host "-> LLM ON, restarting backend..."
    $bpid = Restart-Backend
    if ($bpid) { Write-Host "[ok] LLM ON (pid $bpid). She thinks for real, on Beijing time, ~RMB 0.6/day cap." }
    else { Write-Host "[fail] backend restart failed, see tmp\uvicorn_boot.log.err" }
    Show-Status
  }
  'off' {
    Set-EnvVal 'CONSCIOUSNESS_WORLD_LLM_ENABLED' '0'
    Set-EnvVal 'CONSCIOUSNESS_WORLD_PLANNER_ENABLED' '0'
    Write-Host "-> LLM OFF, restarting backend..."
    $bpid = Restart-Backend
    if ($bpid) { Write-Host "[ok] LLM OFF (pid $bpid). She still lives on free mock, `$0." }
    else { Write-Host "[fail] backend restart failed, see tmp\uvicorn_boot.log.err" }
    Show-Status
  }
  'status' {
    Show-Status
  }
}
