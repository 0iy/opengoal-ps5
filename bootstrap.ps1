# OpenGOAL-PS5 one-liner bootstrap (Windows PowerShell 5.1+). User runs:   irm <BASE>/bootstrap.ps1 | iex
# What it does, nothing else: downloads SHA256SUMS and OpenGOAL-PS5-gui.zip from the same release, checks the zip's SHA-256,
# unpacks it to ~\.opengoal-ps5\app and starts the import window. No admin rights, no system settings changed, no installs.
# Test/override: $env:OGPS5_BASE (other base URL), $env:OGPS5_NORUN=1 (stop after unpacking).
$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
# PLACEHOLDER: replace <owner>/<repo> when the release exists (make_release does not know it).
$Base = if ($env:OGPS5_BASE) { $env:OGPS5_BASE } else { 'https://github.com/<owner>/<repo>/releases/latest/download' }
if ($Base -like '*<owner>*') { throw 'bootstrap.ps1: the download address is still the placeholder <owner>/<repo>. Use the one-liner from the release page.' }
$Dir = Join-Path $HOME '.opengoal-ps5'
$Zip = 'OpenGOAL-PS5-gui.zip'
Write-Host 'OpenGOAL-PS5 will now:' -ForegroundColor Cyan
Write-Host "  1. download $Base/SHA256SUMS and $Base/$Zip"
Write-Host '  2. verify the zip against SHA256SUMS (stops if it does not match)'
Write-Host "  3. unpack it to $Dir\app and open the import window (PowerShell script gui\windows\OpenGOAL-PS5.ps1)"
New-Item -ItemType Directory -Force $Dir | Out-Null
$tmp = Join-Path $Dir 'download'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory $tmp | Out-Null
Invoke-WebRequest -Uri "$Base/SHA256SUMS" -OutFile (Join-Path $tmp 'SHA256SUMS') -UseBasicParsing
Invoke-WebRequest -Uri "$Base/$Zip" -OutFile (Join-Path $tmp $Zip) -UseBasicParsing
$want = Get-Content (Join-Path $tmp 'SHA256SUMS') | Where-Object { $_ -match "^([0-9a-fA-F]{64})\s+\*?$([regex]::Escape($Zip))\s*$" } | ForEach-Object { $Matches[1] } | Select-Object -First 1
$got = (Get-FileHash (Join-Path $tmp $Zip) -Algorithm SHA256).Hash
if (-not $want) { throw "SHA256SUMS has no entry for $Zip. Nothing was run." }
if ($want.ToLower() -ne $got.ToLower()) { throw "SHA-256 mismatch for $Zip (expected $want, got $got). Nothing was run." }
Write-Host "SHA-256 OK: $got" -ForegroundColor Green
$app = Join-Path $Dir 'app'
if (Test-Path $app) { Remove-Item $app -Recurse -Force }
Expand-Archive (Join-Path $tmp $Zip) -DestinationPath $app -Force
Remove-Item $tmp -Recurse -Force
if ($env:OGPS5_NORUN) { Write-Host "Unpacked to $app (OGPS5_NORUN set)."; return }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File (Join-Path $app 'gui\windows\OpenGOAL-PS5.ps1')
