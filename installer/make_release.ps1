# Assemble the installable OpenGOAL-PS5 bundle in release\OpenGOAL-PS5 and zip it.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot             # installer\
$root = Split-Path -Parent $here  # repository root
# the setup script cannot work without the agent payload: stop here instead of shipping a bundle that fails on the user's machine
if (-not (Test-Path "$root\payloads\ogagent.elf")) { throw 'missing payloads\ogagent.elf: build it first (bash payloads/build.sh payloads/ogagent.c payloads/ogagent.elf)' }
$wslHere = (wsl wslpath -a ($root -replace '\\', '/')).Trim()
$out = "$root\release\OpenGOAL-PS5"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force "$out\app", "$out\tools", "$out\payloads" | Out-Null

# the built title folder (eboot.bin, sce_sys, sce_module, assets)
wsl -e bash -lc "rm -rf $wslHere/release/OpenGOAL-PS5/app/LAPY77001 && cp -r ~/ogapp/dist/LAPY77001 $wslHere/release/OpenGOAL-PS5/app/LAPY77001"
Remove-Item -Force -ErrorAction SilentlyContinue "$out\app\LAPY77001\sce_sys\snd0.at9"  # hover music derives from a copyrighted track: never ship it
Copy-Item "$root\payloads\scan.elf" "$out\tools\scan.elf"
Copy-Item "$root\VERSION" "$out\VERSION"; Copy-Item "$root\VERSION" "$out\app\LAPY77001\VERSION"  # the app reports it in /api/info; the setup compares it to decide on an update
Copy-Item "$here\release_template\*" $out -Recurse -Force
# one-liner GUI: gui/, pc_import.py and the bootstrap scripts travel inside the bundle too
Copy-Item "$here\gui" "$out\gui" -Recurse -Force; Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$out\gui\__pycache__"
Copy-Item "$here\bootstrap.ps1", "$here\bootstrap.sh" $out -Force
Copy-Item "$here\pc_import.py", "$here\ps5_setup.py" $out -Force
Copy-Item "$root\payloads\ogagent.elf", "$root\payloads\scan.elf" "$out\payloads" -Force
# licences travel with the binaries (GPL, OFL font notice, third-party notices)
Copy-Item "$root\LICENSE", "$root\THIRD_PARTY_NOTICES.md" $out -Force
Copy-Item "$root\LICENSES" "$out\LICENSES" -Recurse -Force

# SHA256SUMS over every file in the bundle (sha256sum format, forward-slash relative paths)
$sums = Get-ChildItem $out -Recurse -File | Where-Object { $_.Name -ne 'SHA256SUMS' } | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.FullName.Substring($out.Length + 1).Replace('\', '/')
}
[IO.File]::WriteAllText("$out\SHA256SUMS", (($sums -join "`n") + "`n"))

$zip = "$root\release\OpenGOAL-PS5.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$out\*" -DestinationPath $zip
# release assets for the one-liners: OpenGOAL-PS5-gui.zip, bootstrap.ps1/.sh and the release-level SHA256SUMS
python "$here\gui\make_gui_zip.py" "$root\release"
Copy-Item "$root\VERSION" "$root\release\VERSION" -Force  # tiny asset: the update check reads it
"bundle: $zip  ({0:N1} MB)" -f ((Get-Item $zip).Length / 1MB)
Get-ChildItem $out -Recurse -File | Select-Object -First 30 | ForEach-Object { $_.FullName.Substring($out.Length + 1) }
