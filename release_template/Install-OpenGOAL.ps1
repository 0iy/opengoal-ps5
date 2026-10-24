# OpenGOAL-PS5 installer. Run from PowerShell on a PC in the same network as the console:
#
#   .\Install-OpenGOAL.ps1 -Ps5 <ps5-ip>
#
# Needs the jailbroken PS5 running etaHEN with an FTP service on port 2121 and the ELF loader on port 9021.
# It uploads the app and asks the console to register it. Game files are not part of this package: after the
# first start the app shows a QR code, and you send your own .iso images from your phone or PC.
param(
    [Parameter(Mandatory = $true)][string]$Ps5
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function New-FtpRequest($remotePath, $method) {
    $req = [System.Net.FtpWebRequest]::Create("ftp://$Ps5`:2121$remotePath")
    $req.Method = $method
    $req.UseBinary = $true
    $req.UsePassive = $true
    $req.KeepAlive = $true
    return $req
}
function Send-Ftp($localFile, $remotePath) {
    $req = New-FtpRequest $remotePath ([System.Net.WebRequestMethods+Ftp]::UploadFile)
    $in = [IO.File]::OpenRead($localFile)
    $out = $req.GetRequestStream()
    $in.CopyTo($out, 1MB)
    $out.Close(); $in.Close()
    $req.GetResponse().Close()
}
function Make-FtpDir($remotePath) {
    try { (New-FtpRequest $remotePath ([System.Net.WebRequestMethods+Ftp]::MakeDirectory)).GetResponse().Close() } catch { }
}

Write-Host "1/2 Uploading the app to the PS5..." -ForegroundColor Cyan
$app = Join-Path $root 'app\LAPY77001'
Make-FtpDir '/data/homebrew'
Make-FtpDir '/data/homebrew/LAPY77001'
foreach ($dir in Get-ChildItem $app -Recurse -Directory) {
    Make-FtpDir ('/data/homebrew/LAPY77001/' + $dir.FullName.Substring($app.Length + 1).Replace('\', '/'))
}
$files = Get-ChildItem $app -Recurse -File | Sort-Object { $_.Name -in 'eboot.bin', 'param.json' }
foreach ($f in $files) {
    $rel = $f.FullName.Substring($app.Length + 1).Replace('\', '/')
    Send-Ftp $f.FullName "/data/homebrew/LAPY77001/$rel"
    Write-Host "   $rel"
}

Write-Host "2/2 Asking the console to register the app..." -ForegroundColor Cyan
$elf = [IO.File]::ReadAllBytes((Join-Path $root 'tools\scan.elf'))
$c = New-Object System.Net.Sockets.TcpClient($Ps5, 9021)
$st = $c.GetStream(); $st.Write($elf, 0, $elf.Length); $st.Flush(); $c.Close()
Start-Sleep -Seconds 40

Write-Host "Done. Open 'OpenGOAL-PS5' on the PS5 home screen and follow the on-screen steps to add your games." -ForegroundColor Green
