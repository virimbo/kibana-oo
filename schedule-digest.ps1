<#
  schedule-digest.ps1 — turn on the AUTOMATIC daily "documents needing
  attention" digest.

  Run this AFTER set-digest-email.ps1 (or after you've set DIGEST_WEBHOOK_URL).

  What it does:
    1. Asks for a Kibana login the digest can use unattended (your own Kibana
       account is fine) and saves it to .env.
    2. Runs the digest once now, as a test.
    3. Registers a Windows Scheduled Task that runs it every day at 08:00.

  Usage (PowerShell, in the project folder):
    .\schedule-digest.ps1                 # daily at 08:00
    .\schedule-digest.ps1 -At "07:30"     # custom time
#>
param(
  [string]$KibanaUser,
  [string]$KibanaPassword,
  [string]$At = "08:00",
  [string]$TaskName = "KIBANA-OO Daily Digest"
)

$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot ".env"

if (-not $KibanaUser) { $KibanaUser = Read-Host "Kibana username for the unattended digest (e.g. you@koop.overheid.nl)" }
$KibanaUser = $KibanaUser.Trim()
if (-not $KibanaPassword) {
  $secure = Read-Host "Kibana password (hidden)" -AsSecureString
  $KibanaPassword = [System.Net.NetworkCredential]::new("", $secure).Password
}
if (-not $KibanaUser -or -not $KibanaPassword) {
  Write-Host "Kibana username and password are required. Nothing changed." -ForegroundColor Yellow; exit 1
}

# Upsert the service-account creds in .env
$settings = [ordered]@{ DIGEST_KIBANA_USER = $KibanaUser; DIGEST_KIBANA_PASSWORD = $KibanaPassword }
$lines = if (Test-Path $envFile) { Get-Content $envFile } else { @() }
foreach ($key in $settings.Keys) {
  $val = $settings[$key]; $found = $false
  $lines = $lines | ForEach-Object { if ($_ -match "^\s*$key\s*=") { $found = $true; "$key=$val" } else { $_ } }
  if (-not $found) { $lines = @($lines) + "$key=$val" }
}
($lines -join "`n") + "`n" | Set-Content -Path $envFile -NoNewline -Encoding utf8

Write-Host "Restarting backend so it has the credentials..." -ForegroundColor Cyan
docker compose up -d --force-recreate backend | Out-Null
Start-Sleep -Seconds 6

Write-Host "Running the digest once as a test..." -ForegroundColor Cyan
docker compose exec -T backend python send_digest.py
if ($LASTEXITCODE -ne 0) {
  Write-Host "Test run failed (exit $LASTEXITCODE). Check that email/webhook is configured (run set-digest-email.ps1) and the Kibana login is correct. Task NOT scheduled." -ForegroundColor Red
  exit 1
}
Write-Host "Test digest sent." -ForegroundColor Green

# Register the daily Windows Scheduled Task
$proj = $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -WindowStyle Hidden -Command `"Set-Location '$proj'; docker compose exec -T backend python send_digest.py`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settingsTask = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settingsTask -Force | Out-Null

Write-Host "Done. The digest will be sent every day at $At." -ForegroundColor Green
Write-Host "  (Requires Docker Desktop to be running. Manage/remove the task in Task Scheduler under '$TaskName'.)" -ForegroundColor DarkGray
