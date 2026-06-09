<#
  set-mistral-key.ps1 — safely install a Mistral API key.

  What it does:
    1. Asks for your Mistral API key (or takes it as an argument).
    2. Tests it LIVE against the Mistral API.
    3. Only if the key works (HTTP 200): writes it into .env and restarts the backend.
    If the key is rejected it refuses to save, so you never get stuck on a bad key again.

  Usage (from PowerShell, in the project folder):
    .\set-mistral-key.ps1
  or:
    .\set-mistral-key.ps1 -Key "your-key-here"

  Get a key at: https://console.mistral.ai/api-keys/
#>
param(
  [string]$Key,
  [string]$Model = "mistral-large-latest"
)

$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot ".env"

if (-not $Key) {
  $secure = Read-Host "Paste your Mistral API key" -AsSecureString
  $Key = [System.Net.NetworkCredential]::new("", $secure).Password
}
$Key = $Key.Trim()
if (-not $Key) { Write-Host "No key entered. Nothing changed." -ForegroundColor Yellow; exit 1 }

Write-Host "Testing the key against Mistral..." -ForegroundColor Cyan
$body = @{
  model    = $Model
  messages = @(@{ role = "user"; content = "ping" })
  max_tokens = 5
} | ConvertTo-Json -Depth 5

try {
  $resp = Invoke-WebRequest -Uri "https://api.mistral.ai/v1/chat/completions" `
    -Method Post `
    -Headers @{ Authorization = "Bearer $Key" } `
    -ContentType "application/json" `
    -Body $body `
    -TimeoutSec 30
  $status = [int]$resp.StatusCode
} catch {
  $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
}

if ($status -ne 200) {
  switch ($status) {
    401 { Write-Host "REJECTED (401 Unauthorized): the key is wrong or revoked. Not saved." -ForegroundColor Red }
    403 { Write-Host "REJECTED (403 Forbidden): key valid but no access/billing. Not saved." -ForegroundColor Red }
    429 { Write-Host "RATE-LIMITED (429): key looks valid but is throttled. Try again shortly. Not saved." -ForegroundColor Yellow }
    0   { Write-Host "Could not reach Mistral (no network / VPN?). Not saved." -ForegroundColor Red }
    default { Write-Host "Mistral returned HTTP $status. Not saved." -ForegroundColor Red }
  }
  exit 1
}

Write-Host "Key works (HTTP 200). Saving to .env..." -ForegroundColor Green

# Upsert MISTRAL_API_KEY in .env (preserve everything else; LF line endings).
$lines = if (Test-Path $envFile) { Get-Content $envFile } else { @() }
$found = $false
$out = foreach ($line in $lines) {
  if ($line -match '^\s*MISTRAL_API_KEY\s*=') { $found = $true; "MISTRAL_API_KEY=$Key" }
  else { $line }
}
if (-not $found) { $out = @($out) + "MISTRAL_API_KEY=$Key" }
($out -join "`n") + "`n" | Set-Content -Path $envFile -NoNewline -Encoding utf8

Write-Host "Recreating the backend so it picks up the new key..." -ForegroundColor Cyan
docker compose up -d --force-recreate backend | Out-Null

Write-Host "Done. Mistral is installed and verified working." -ForegroundColor Green
