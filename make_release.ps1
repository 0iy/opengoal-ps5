# Assemble the installable OpenGOAL-PS5 bundle in release\OpenGOAL-PS5 and zip it.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$wslHere = (wsl wslpath -a ($here -replace '\\', '/')).Trim()
$out = "$here\release\OpenGOAL-PS5"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force "$out\app", "$out\tools" | Out-Null

# the built title folder (eboot.bin, sce_sys, sce_module, assets)
wsl -e bash -lc "rm -rf $wslHere/release/OpenGOAL-PS5/app/LAPY77001 && cp -r ~/ogapp/dist/LAPY77001 $wslHere/release/OpenGOAL-PS5/app/LAPY77001"
Remove-Item -Force -ErrorAction SilentlyContinue "$out\app\LAPY77001\sce_sys\snd0.at9"  # hover music derives from a copyrighted track: never ship it
Copy-Item "$here\m1\scan.elf" "$out\tools\scan.elf"
Copy-Item "$here\upload_data.py" "$out\tools\upload_data.py"
Copy-Item "$here\release_template\*" $out -Recurse -Force
# one-liner GUI: gui/, pc_import.py (when it exists) and the bootstrap scripts travel inside the bundle too
Copy-Item "$here\gui" "$out\gui" -Recurse -Force; Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$out\gui\__pycache__"
Copy-Item "$here\bootstrap.ps1", "$here\bootstrap.sh" $out -Force
if (Test-Path "$here\pc_import.py") { Copy-Item "$here\pc_import.py" $out -Force } else { Write-Warning 'pc_import.py missing, bundle has no import engine' }

# SHA256SUMS over every file in the bundle (sha256sum format, forward-slash relative paths)
$sums = Get-ChildItem $out -Recurse -File | Where-Object { $_.Name -ne 'SHA256SUMS' } | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.FullName.Substring($out.Length + 1).Replace('\', '/')
}
[IO.File]::WriteAllText("$out\SHA256SUMS", (($sums -join "`n") + "`n"))

$zip = "$here\release\OpenGOAL-PS5.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$out\*" -DestinationPath $zip
# release assets for the one-liners: OpenGOAL-PS5-gui.zip, bootstrap.ps1/.sh and the release-level SHA256SUMS
python "$here\gui\make_gui_zip.py" "$here\release"
"bundle: $zip  ({0:N1} MB)" -f ((Get-Item $zip).Length / 1MB)
Get-ChildItem $out -Recurse -File | Select-Object -First 30 | ForEach-Object { $_.FullName.Substring($out.Length + 1) }
