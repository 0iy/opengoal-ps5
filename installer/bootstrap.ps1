# OpenGOAL-PS5 one-liner bootstrap (Windows PowerShell 5.1+). User runs:   irm <BASE>/bootstrap.ps1 | iex
# What it does, nothing else: downloads SHA256SUMS and OpenGOAL-PS5-gui.zip from the same release, checks the zip's SHA-256,
# unpacks it to ~\.opengoal-ps5\app and starts the import window. No admin rights, no system settings changed, no installs.
# Test/override: $env:OGPS5_BASE (other base URL), $env:OGPS5_NORUN=1 (stop after unpacking).
$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
$Base = if ($env:OGPS5_BASE) { $env:OGPS5_BASE } else { 'https://github.com/0iy/opengoal-ps5/releases/latest/download' }
$Dir = Join-Path $HOME '.opengoal-ps5'
$Zip = 'OpenGOAL-PS5-gui.zip'
Write-Host 'OpenGOAL-PS5 will now:' -ForegroundColor Cyan
Write-Host "  1. download $Base/SHA256SUMS and $Base/$Zip"
Write-Host '  2. verify the zip against SHA256SUMS (stops if it does not match)'
Write-Host "  3. unpack it to $Dir\app, run the console setup (ps5_setup.py: finds the PS5, installs what is missing; set OGPS5_SKIP_SETUP=1 to skip)"
Write-Host '  4. open the import window (PowerShell script gui\windows\OpenGOAL-PS5.ps1)'
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
if (-not $env:OGPS5_SKIP_SETUP) {
    $py = $null
    $portable = Join-Path $Dir 'python\python.exe'  # the import window's own portable Python, if an earlier run fetched it
    if (Test-Path $portable) { $py = $portable }
    foreach ($n in 'python', 'python3', 'py') {
        $c = Get-Command $n -ErrorAction SilentlyContinue | Select-Object -First 1
        # the Microsoft Store stub is found by name but cannot run: require a real Python 3.7+
        if ($c -and -not $py) { & $c.Source -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' 2>$null; if ($LASTEXITCODE -eq 0) { $py = $c.Source } }
    }
    if ($py) {
        & $py (Join-Path $app 'ps5_setup.py')
        if ($LASTEXITCODE -ne 0) { Write-Host "The console setup did not finish. Run it again: $py $app\ps5_setup.py" -ForegroundColor Yellow; return }
    } else {
        Write-Host 'Python 3 not found: the console setup is skipped for now. The import window offers to fetch a Python; afterwards run this line again, or install it yourself: winget install Python.Python.3.12 --scope user' -ForegroundColor Yellow
    }
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File (Join-Path $app 'gui\windows\OpenGOAL-PS5.ps1')
