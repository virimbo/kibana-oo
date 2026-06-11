<#
  set-digest-email.ps1 — set up the "documents needing attention" email digest
  with your Gmail account.

  What it does:
    1. Asks for your Gmail address and a Google APP PASSWORD (16 chars).
    2. Sends a TEST email to yourself to prove it works.
    3. Only if the test succeeds: writes the SMTP settings into .env and
       restarts the backend.

  Get an app password (one-time):
    Google Account -> Security -> 2-Step Verification (must be ON)
      -> App passwords -> create one (name it "kibana-oo") -> copy the 16 chars.

  Usage (PowerShell, in the project folder):
    .\set-digest-email.ps1
#>
param(
  [string]$Gmail,
  [string]$AppPassword,
  [string]$Recipients   # optional; defaults to your Gmail address
)

$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot ".env"

if (-not $Gmail)       { $Gmail = Read-Host "Your Gmail address (e.g. you@gmail.com)" }
$Gmail = $Gmail.Trim()
if (-not $AppPassword) {
  $secure = Read-Host "Your Google APP PASSWORD (16 chars, hidden)" -AsSecureString
  $AppPassword = [System.Net.NetworkCredential]::new("", $secure).Password
}
$AppPassword = ($AppPassword -replace '\s', '')   # Google shows it with spaces
if (-not $Recipients) { $Recipients = $Gmail }

if (-not $Gmail -or -not $AppPassword) {
  Write-Host "Gmail address and app password are required. Nothing changed." -ForegroundColor Yellow
  exit 1
}

Write-Host "Sending a test email to $Recipients ..." -ForegroundColor Cyan
try {
  $msg = New-Object System.Net.Mail.MailMessage
  $msg.From = $Gmail
  foreach ($r in ($Recipients -split ',')) { if ($r.Trim()) { $msg.To.Add($r.Trim()) } }
  $msg.Subject = "KIBANA-OO digest — test email ✅"
  $msg.Body = "This is a test from KIBANA-OO. If you can read this, your daily 'documents needing attention' digest is ready to go."

  $smtp = New-Object System.Net.Mail.SmtpClient("smtp.gmail.com", 587)
  $smtp.EnableSsl = $true
  $smtp.Credentials = New-Object System.Net.NetworkCredential($Gmail, $AppPassword)
  $smtp.Send($msg)
} catch {
  Write-Host "REJECTED: the test email could not be sent. Not saved." -ForegroundColor Red
  Write-Host ("  " + $_.Exception.Message) -ForegroundColor Red
  Write-Host "  Most common cause: that's your normal password, not a 16-char APP password," -ForegroundColor Yellow
  Write-Host "  or 2-Step Verification isn't enabled. See the header of this script." -ForegroundColor Yellow
  exit 1
}

Write-Host "Test email sent (check your inbox). Saving settings to .env..." -ForegroundColor Green

# Upsert the SMTP keys in .env (preserve everything else; LF endings).
$settings = [ordered]@{
  SMTP_HOST          = "smtp.gmail.com"
  SMTP_PORT          = "587"
  SMTP_USER          = $Gmail
  SMTP_PASSWORD      = $AppPassword
  SMTP_FROM          = $Gmail
  SMTP_USE_TLS       = "true"
  DIGEST_RECIPIENTS  = $Recipients
}
$lines = if (Test-Path $envFile) { Get-Content $envFile } else { @() }
foreach ($key in $settings.Keys) {
  $val = $settings[$key]
  $found = $false
  $lines = $lines | ForEach-Object {
    if ($_ -match "^\s*$key\s*=") { $found = $true; "$key=$val" } else { $_ }
  }
  if (-not $found) { $lines = @($lines) + "$key=$val" }
}
($lines -join "`n") + "`n" | Set-Content -Path $envFile -NoNewline -Encoding utf8

Write-Host "Recreating the backend so it picks up the settings..." -ForegroundColor Cyan
docker compose up -d --force-recreate backend | Out-Null

Write-Host "Done. The email digest is configured." -ForegroundColor Green
Write-Host "Now: open the dashboard and click '📧 Send me this digest' to send the live list." -ForegroundColor Green
