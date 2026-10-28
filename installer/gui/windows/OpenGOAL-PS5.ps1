# OpenGOAL-PS5 import GUI (Windows PowerShell 5.1+, WinForms, no extra installs except Python 3 for pc_import.py).
# Drop your own Jak .iso files, the PS5 is found on the local network, the PC does the heavy work and sends the result.
# Test hooks: -Iso/-Ps5/-AutoStart/-ScreenshotTo, env OGPS5_ENGINE (engine script), OGPS5_PORT, OGPS5_SCAN_PREFIX ("127.0.0."), OGPS5_LANG.
param(
    [string[]]$Iso = @(),
    [string]$Ps5 = '',
    [switch]$AutoStart,
    [string]$ScreenshotTo = ''
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::SetUnhandledExceptionMode('CatchException')
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$Home5 = Join-Path $HOME '.opengoal-ps5'
$CfgFile = Join-Path $Home5 'config.json'
$Port = 8080
if ($env:OGPS5_PORT) { $Port = [int]$env:OGPS5_PORT }
# Portable Python for machines without one: the official embeddable zip, accepted only when its sha256 matches (docs/INSTALL.md).
$PyEmbedUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'
$PyEmbedSha256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'

# ---------- language ----------
$lang = [Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName
if ($env:OGPS5_LANG) { $lang = $env:OGPS5_LANG }
$de = ($lang -eq 'de')
$S = @{
    title   = @('OpenGOAL-PS5: import your games', 'OpenGOAL-PS5: Spiele importieren')
    upd     = @('Update available: {0} (you have {1}). Run the install command again.', 'Update verfuegbar: {0} (installiert {1}). Installationsbefehl erneut ausfuehren.')
    drop    = @('Drop your Jak .iso files here', 'Jak-.iso-Dateien hier ablegen')
    browse  = @('Browse...', 'Durchsuchen...')
    ps5     = @('PS5 address', 'PS5-Adresse')
    find    = @('Find PS5', 'PS5 suchen')
    test    = @('Test connection', 'Verbindung testen')
    start   = @('Start', 'Starten')
    cancel  = @('Cancel', 'Abbrechen')
    finding = @('Searching the network...', 'Suche im Netzwerk...')
    notfound = @('No PS5 found. Start OpenGOAL-PS5 on the console, or type its IP address.', 'Keine PS5 gefunden. OpenGOAL-PS5 auf der Konsole starten oder die IP eintippen.')
    found   = @('PS5 found: ', 'PS5 gefunden: ')
    okconn  = @('Connected: OpenGOAL-PS5 answers.', 'Verbunden: OpenGOAL-PS5 antwortet.')
    badconn = @('No answer. Is OpenGOAL-PS5 running on the console (home screen app) and is the PC on the same network?', 'Keine Antwort. Laeuft OpenGOAL-PS5 auf der Konsole und ist der PC im selben Netzwerk?')
    badip   = @('Enter the PS5 IP address first (or press Find PS5).', 'Zuerst die PS5-IP eintragen (oder PS5 suchen).')
    nogames = @('Add at least one valid game image first.', 'Zuerst mindestens ein gueltiges Spiel-Image hinzufuegen.')
    unknown = @('Not a Jak and Daxter disc image.', 'Kein Jak-and-Daxter-Disc-Image.')
    notiso  = @('Not an ISO image (a .bin/.cue must be converted to .iso first).', 'Kein ISO-Image (.bin/.cue zuerst in .iso umwandeln).')
    trunc   = @('The file is smaller than the disc image says: incomplete copy.', 'Die Datei ist kleiner als das Image angibt: unvollstaendige Kopie.')
    dup     = @('Another image for this game is already in the list.', 'Fuer dieses Spiel ist schon ein Image in der Liste.')
    ready   = @('Ready to start', 'Bereit')
    waiting = @('Waiting', 'Wartet')
    done    = @('Done', 'Fertig')
    failed  = @('Failed', 'Fehlgeschlagen')
    cancelled = @('Cancelled', 'Abgebrochen')
    success = @('Ready: start the game on your PS5.', 'Fertig: Starte jetzt das Spiel auf deiner PS5.')
    partial = @('Some games failed. The others are ready on your PS5.', 'Einige Spiele sind fehlgeschlagen. Die anderen sind auf deiner PS5 bereit.')
    nopy    = @('Python 3 is needed for the conversion and was not found.', 'Fuer die Umwandlung wird Python 3 gebraucht, es wurde nicht gefunden.')
    pyask1  = @("Python 3 is missing.`n`nYes: install it with winget (per user, no admin)`nNo: download a portable copy (no admin)`nCancel: stop", "Python 3 fehlt.`n`nJa: mit winget installieren (nur fuer dich, kein Admin)`nNein: portable Kopie herunterladen (kein Admin)`nAbbrechen: beenden")
    pyask2  = @("Python 3 is missing. Download a portable copy (about 10 MB, no admin)?", "Python 3 fehlt. Eine portable Kopie laden (ca. 10 MB, kein Admin)?")
    pyfail  = @('Could not set up Python. Install Python 3 from python.org (tick "Add to PATH") and start again.', 'Python konnte nicht eingerichtet werden. Python 3 von python.org installieren (Haken bei "Add to PATH") und neu starten.')
    noengine = @('The import engine (pc_import.py) was not found next to this program. Download the full bundle again.', 'Die Import-Engine (pc_import.py) wurde nicht gefunden. Das komplette Paket neu herunterladen.')
    hint_conn = @('Check that OpenGOAL-PS5 is open on the console and that PC and PS5 are on the same network.', 'Pruefe, ob OpenGOAL-PS5 auf der Konsole offen ist und PC und PS5 im selben Netzwerk sind.')
    hint_space = @('The console may be out of free disk space.', 'Auf der Konsole ist eventuell zu wenig Speicher frei.')
    hint_disc = @('The disc image may be damaged or not a supported version. Make a fresh copy of your disc.', 'Das Image ist eventuell beschaedigt oder keine unterstuetzte Version. Erstelle eine neue Kopie deiner Disc.')
    hint_any = @('Details are in the line above. You can start again; finished steps are reused.', 'Details stehen in der Zeile oben. Du kannst erneut starten.')
    sel_title = @('Choose your game image(s)', 'Spiel-Image(s) waehlen')
    phase_detect = @('Checking image', 'Pruefe Image')
    phase_tools = @('Preparing tools', 'Bereite Werkzeuge vor')
    phase_extract = @('Unpacking', 'Entpacke')
    phase_decompile = @('Analysing game', 'Analysiere Spiel')
    phase_compile = @('Building game', 'Baue Spiel')
    phase_pack = @('Packing', 'Packe')
    phase_upload = @('Sending to PS5', 'Sende an PS5')
    phase_install = @('Installing on PS5', 'Installiere auf PS5')
    phase_done = @('Done', 'Fertig')
    phase_failed = @('Failed', 'Fehlgeschlagen')
    left    = @('left', 'verbleibend')
}
function T([string]$k) { if ($de) { $S[$k][1] } else { $S[$k][0] } }
$GameName = @{ jak1 = 'Jak and Daxter'; jak2 = 'Jak II'; jak3 = 'Jak 3' }
# Serial table: same as app/shim/importer.cpp.
$Discs = @{
    'SCUS-97124' = @('jak1', 'NTSC-U'); 'SCES-50361' = @('jak1', 'PAL'); 'SCPS-15021' = @('jak1', 'NTSC-J'); 'SCPS-56003' = @('jak1', 'NTSC-K')
    'SCUS-97265' = @('jak2', 'NTSC-U'); 'SCES-51608' = @('jak2', 'PAL'); 'SCPS-15057' = @('jak2', 'NTSC-J'); 'SCKA-20010' = @('jak2', 'NTSC-K')
    'SCUS-97330' = @('jak3', 'NTSC-U'); 'SCUS-97516' = @('jak3', 'NTSC-U'); 'SCES-52460' = @('jak3', 'PAL'); 'SCKA-20040' = @('jak3', 'NTSC-K')
}

# ---------- config ----------
function Load-Cfg { try { Get-Content $CfgFile -Raw | ConvertFrom-Json } catch { $null } }
function Save-Ip([string]$ip) {
    try { New-Item -ItemType Directory -Force $Home5 | Out-Null; (@{ ps5 = $ip } | ConvertTo-Json) | Set-Content $CfgFile -Encoding UTF8 } catch { }
}

# ---------- ISO9660 detection (reads about 6 KB, no hashing) ----------
# Returns @{ok=$true; game; serial; region} or @{ok=$false; reason=<key of $S>}.
function Get-IsoInfo([string]$path) {
    $fs = $null
    try {
        if ($path -notmatch '\.iso$') { return @{ ok = $false; reason = 'notiso' } }
        $fs = [IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
        $rd = {
            param([long]$off, [int]$n)
            $b = New-Object byte[] $n
            $null = $fs.Seek($off, 'Begin'); $got = $fs.Read($b, 0, $n)
            if ($got -lt $n) { [Array]::Resize([ref]$b, $got) }
            , $b
        }
        $pvd = & $rd (16 * 2048) 2048
        if ($pvd.Length -lt 2048 -or $pvd[0] -ne 1 -or [Text.Encoding]::ASCII.GetString($pvd, 1, 5) -ne 'CD001') { return @{ ok = $false; reason = 'notiso' } }
        $volBlocks = [BitConverter]::ToUInt32($pvd, 80)
        if ([long]$volBlocks * 2048 -gt $fs.Length) { return @{ ok = $false; reason = 'trunc' } }
        $rootLba = [BitConverter]::ToUInt32($pvd, 156 + 2); $rootLen = [Math]::Min([BitConverter]::ToUInt32($pvd, 156 + 10), 262144)
        $dir = & $rd ([long]$rootLba * 2048) ([int]$rootLen)
        $p = 0; $cnf = $null
        while ($p -lt $dir.Length) {
            $l = $dir[$p]
            if ($l -eq 0) { $p = ([int][Math]::Floor($p / 2048) + 1) * 2048; continue }
            $nl = $dir[$p + 32]
            if ([Text.Encoding]::ASCII.GetString($dir, $p + 33, $nl) -eq 'SYSTEM.CNF;1') {
                $cnf = & $rd ([long][BitConverter]::ToUInt32($dir, $p + 2) * 2048) ([int][Math]::Min([BitConverter]::ToUInt32($dir, $p + 10), 4096))
                break
            }
            $p += $l
        }
        if (-not $cnf) { return @{ ok = $false; reason = 'unknown' } }
        $txt = [Text.Encoding]::ASCII.GetString($cnf)
        if ($txt -notmatch 'cdrom0:\\?([A-Z]{4})_(\d{3})\.(\d{2})') { return @{ ok = $false; reason = 'unknown' } }
        $serial = '{0}-{1}{2}' -f $Matches[1], $Matches[2], $Matches[3]
        if (-not $Discs.ContainsKey($serial)) { return @{ ok = $false; reason = 'unknown' } }
        return @{ ok = $true; game = $Discs[$serial][0]; region = $Discs[$serial][1]; serial = $serial }
    } catch { return @{ ok = $false; reason = 'notiso' } }
    finally { if ($fs) { $fs.Dispose() } }
}

# ---------- PS5 discovery ----------
function Test-Ps5([string]$ip) {
    try {
        $r = [Net.HttpWebRequest]::Create("http://${ip}:$Port/api/status"); $r.Timeout = 2000; $r.ReadWriteTimeout = 2000
        $resp = $r.GetResponse(); $sr = New-Object IO.StreamReader($resp.GetResponseStream())
        $body = $sr.ReadToEnd(); $sr.Dispose(); $resp.Close()
        if ($body -match '"version"') { return $true }
    } catch { }
    return $false
}
function Find-Ps5 {
    $prefixes = @()
    if ($env:OGPS5_SCAN_PREFIX) { $prefixes = @($env:OGPS5_SCAN_PREFIX) }
    else {
        foreach ($ni in [Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
            if ($ni.OperationalStatus -ne 'Up' -or $ni.NetworkInterfaceType -eq 'Loopback') { continue }
            foreach ($ua in $ni.GetIPProperties().UnicastAddresses) {
                if ($ua.Address.AddressFamily -eq 'InterNetwork') { $b = $ua.Address.GetAddressBytes(); $prefixes += ('{0}.{1}.{2}.' -f $b[0], $b[1], $b[2]) }
            }
        }
    }
    $jobs = @()
    foreach ($pre in ($prefixes | Select-Object -Unique)) {
        foreach ($i in 1..254) { $c = New-Object Net.Sockets.TcpClient; $jobs += , @{ ip = "$pre$i"; c = $c; t = $c.ConnectAsync("$pre$i", $Port) } }
    }
    try { [void][Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($jobs | ForEach-Object { $_.t }), 1200) } catch { }
    $hit = $null
    foreach ($j in $jobs) { if (-not $hit -and $j.t.Status -eq 'RanToCompletion' -and $j.c.Connected -and (Test-Ps5 $j.ip)) { $hit = $j.ip } }
    foreach ($j in $jobs) { try { $j.c.Dispose() } catch { } }
    $hit
}

# ---------- Python ----------
function Test-Py($exe, $pre) {
    try { $o = & $exe @pre -c "import sys;print(sys.version_info[0])" 2>$null; return ("$o".Trim() -eq '3') } catch { return $false }
}
function Find-Python {
    $cands = @(
        @((Join-Path $Home5 'python\python.exe'), @()),
        @('py', @('-3')), @('python', @()), @('python3', @()),
        @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'), @())
    )
    foreach ($c in $cands) { if (Test-Py $c[0] $c[1]) { return $c } }
    $null
}
function Install-Python {
    $hasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
    $mode = 'portable'
    if ($hasWinget) {
        $a = [Windows.Forms.MessageBox]::Show((T 'pyask1'), 'OpenGOAL-PS5', 'YesNoCancel', 'Question')
        if ($a -eq 'Cancel') { return $false }
        if ($a -eq 'Yes') { $mode = 'winget' }
    } else {
        if ([Windows.Forms.MessageBox]::Show((T 'pyask2'), 'OpenGOAL-PS5', 'YesNo', 'Question') -ne 'Yes') { return $false }
    }
    $form.Cursor = 'WaitCursor'
    try {
        if ($mode -eq 'winget') {
            $p = Start-Process winget -ArgumentList 'install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements' -Wait -PassThru -WindowStyle Hidden
            return ($p.ExitCode -eq 0 -and [bool](Find-Python))
        }
        if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { return $false }
        New-Item -ItemType Directory -Force $Home5 | Out-Null
        $zip = Join-Path $Home5 'python-embed.zip'
        Invoke-WebRequest -Uri $PyEmbedUrl -OutFile $zip -UseBasicParsing
        if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne $PyEmbedSha256.ToLower()) { Remove-Item $zip -Force; return $false }
        $dest = Join-Path $Home5 'python'
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Expand-Archive $zip -DestinationPath $dest -Force; Remove-Item $zip -Force
        return [bool](Find-Python)
    } catch { return $false } finally { $form.Cursor = 'Default' }
}
function Find-Engine {
    if ($env:OGPS5_ENGINE) { return $env:OGPS5_ENGINE }
    foreach ($d in @($PSScriptRoot, (Split-Path $PSScriptRoot), (Split-Path (Split-Path $PSScriptRoot)))) {
        $f = Join-Path $d 'pc_import.py'; if (Test-Path $f) { return $f }
    }
    $null
}

# ---------- child process with a thread-safe line queue (event handlers on pool threads cannot run scriptblocks) ----------
if (-not ('OgProc' -as [type])) {
    Add-Type -TypeDefinition @'
using System; using System.Collections.Concurrent; using System.Diagnostics; using System.Text;
public class OgProc {
    public Process P; public ConcurrentQueue<string> Out = new ConcurrentQueue<string>();
    public static OgProc Start(string exe, string args) {
        var o = new OgProc();
        var psi = new ProcessStartInfo(exe, args);
        psi.UseShellExecute = false; psi.CreateNoWindow = true;
        psi.RedirectStandardOutput = true; psi.RedirectStandardError = true;
        psi.StandardOutputEncoding = Encoding.UTF8; psi.StandardErrorEncoding = Encoding.UTF8;
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"; psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
        o.P = new Process(); o.P.StartInfo = psi;
        o.P.OutputDataReceived += (s, e) => { if (e.Data != null) o.Out.Enqueue(e.Data); };
        o.P.ErrorDataReceived += (s, e) => { if (e.Data != null) o.Out.Enqueue("ERR " + e.Data); };
        o.P.Start(); o.P.BeginOutputReadLine(); o.P.BeginErrorReadLine();
        return o;
    }
}
'@
}

# ---------- UI ----------
$Bg = [Drawing.Color]::FromArgb(20, 22, 26); $Panel = [Drawing.Color]::FromArgb(32, 35, 41); $Track = [Drawing.Color]::FromArgb(52, 56, 64)
$Orange = [Drawing.Color]::FromArgb(255, 138, 0); $Fg = [Drawing.Color]::FromArgb(235, 235, 235); $Dim = [Drawing.Color]::FromArgb(150, 155, 165)
$Green = [Drawing.Color]::FromArgb(70, 200, 110); $Red = [Drawing.Color]::FromArgb(235, 85, 70)
$font = New-Object Drawing.Font('Segoe UI', 10); $fontB = New-Object Drawing.Font('Segoe UI Semibold', 10); $fontH = New-Object Drawing.Font('Segoe UI Semibold', 16)

function New-Label($text, $x, $y, $w, $h, $color, $f) {
    $l = New-Object Windows.Forms.Label; $l.Text = $text; $l.Location = New-Object Drawing.Point($x, $y); $l.Size = New-Object Drawing.Size($w, $h)
    $l.ForeColor = $color; $l.BackColor = [Drawing.Color]::Transparent; $l.Font = $f; $l
}
function New-Button($text, $x, $y, $w, $primary) {
    $b = New-Object Windows.Forms.Button; $b.Text = $text; $b.Location = New-Object Drawing.Point($x, $y); $b.Size = New-Object Drawing.Size($w, 32)
    $b.FlatStyle = 'Flat'; $b.FlatAppearance.BorderSize = 0; $b.Font = $fontB; $b.Cursor = 'Hand'
    if ($primary) { $b.BackColor = $Orange; $b.ForeColor = [Drawing.Color]::FromArgb(20, 20, 20) } else { $b.BackColor = $Track; $b.ForeColor = $Fg }
    $b
}

$form = New-Object Windows.Forms.Form
$form.Text = 'OpenGOAL-PS5'; $form.ClientSize = New-Object Drawing.Size(720, 640); $form.StartPosition = 'CenterScreen'
$form.BackColor = $Bg; $form.ForeColor = $Fg; $form.Font = $font; $form.AllowDrop = $true
$form.FormBorderStyle = 'FixedSingle'; $form.MaximizeBox = $false

$form.Controls.Add((New-Label (T 'title') 20 14 680 32 $Orange $fontH))
$updLbl = New-Label '' 20 40 680 18 $Green $font; $updLbl.TextAlign = 'MiddleRight'; $form.Controls.Add($updLbl)  # filled by the update check at startup

# drop zone
$drop = New-Object Windows.Forms.Panel; $drop.Location = New-Object Drawing.Point(20, 56); $drop.Size = New-Object Drawing.Size(680, 90); $drop.AllowDrop = $true; $drop.BackColor = $Panel
$drop.Add_Paint({
    param($s, $e)
    $pen = New-Object Drawing.Pen($Orange, 2); $pen.DashStyle = 'Dash'
    $e.Graphics.DrawRectangle($pen, 2, 2, $s.Width - 5, $s.Height - 5); $pen.Dispose()
})
$dropLbl = New-Label (T 'drop') 0 18 680 28 $Fg $fontB; $dropLbl.TextAlign = 'MiddleCenter'; $drop.Controls.Add($dropLbl)
$browse = New-Button (T 'browse') 270 52 140 $false; $drop.Controls.Add($browse)
$form.Controls.Add($drop)

# cards
$cards = New-Object Windows.Forms.Panel; $cards.Location = New-Object Drawing.Point(20, 158); $cards.Size = New-Object Drawing.Size(680, 270); $cards.AutoScroll = $true; $cards.BackColor = $Bg
$form.Controls.Add($cards)

# PS5 row
$form.Controls.Add((New-Label (T 'ps5') 20 440 110 24 $Dim $font))
$ipBox = New-Object Windows.Forms.TextBox; $ipBox.Location = New-Object Drawing.Point(130, 437); $ipBox.Size = New-Object Drawing.Size(150, 28)
$ipBox.BackColor = $Panel; $ipBox.ForeColor = $Fg; $ipBox.BorderStyle = 'FixedSingle'; $form.Controls.Add($ipBox)
$findBtn = New-Button (T 'find') 292 434 120 $false; $form.Controls.Add($findBtn)
$testBtn = New-Button (T 'test') 422 434 150 $false; $form.Controls.Add($testBtn)
$netLbl = New-Label '' 20 472 680 44 $Dim $font; $form.Controls.Add($netLbl)

# overall + result
$allBar = New-Object Windows.Forms.Panel; $allBar.Location = New-Object Drawing.Point(20, 524); $allBar.Size = New-Object Drawing.Size(680, 8); $allBar.BackColor = $Track
$allFill = New-Object Windows.Forms.Panel; $allFill.Dock = 'Left'; $allFill.Width = 0; $allFill.BackColor = $Orange; $allBar.Controls.Add($allFill); $form.Controls.Add($allBar)
$result = New-Label '' 20 540 680 52 $Fg $fontB; $form.Controls.Add($result)
$startBtn = New-Button (T 'start') 20 598 150 $true; $form.Controls.Add($startBtn)
$cancelBtn = New-Button (T 'cancel') 180 598 130 $false; $cancelBtn.Enabled = $false; $form.Controls.Add($cancelBtn)

# ---------- cards logic ----------
$script:items = New-Object System.Collections.ArrayList
$script:running = $false
function Set-Bar($it, [int]$pct) { $it.fill.Width = [int]($it.bar.Width * [Math]::Max(0, [Math]::Min(100, $pct)) / 100) }
function Relayout { $y = 0; foreach ($it in $script:items) { $it.panel.Top = $y; $y += 88 } }
function Add-Iso([string]$path) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return }
    foreach ($e in $script:items) { if ($e.path -eq $path) { return } }
    $info = Get-IsoInfo $path
    $err = ''
    if (-not $info.ok) { $err = T $info.reason }
    else { foreach ($e in $script:items) { if ($e.ok -and $e.game -eq $info.game) { $err = T 'dup' } } }
    $p = New-Object Windows.Forms.Panel; $p.Size = New-Object Drawing.Size(660, 80); $p.BackColor = $Panel
    $title = ''
    if ($err -eq '' -or $info.ok) { $title = '{0}   ({1}, {2})' -f $GameName[$info.game], $info.region, $info.serial } else { $title = [IO.Path]::GetFileName($path) }
    if ($info.ok -and $err -ne '') { $title = '{0}   ({1})' -f $GameName[$info.game], [IO.Path]::GetFileName($path) }
    $tl = New-Label $title 12 8 560 22 $Fg $fontB
    $fl = New-Label ([IO.Path]::GetFileName($path)) 12 28 560 18 $Dim $font; $fl.Font = New-Object Drawing.Font('Segoe UI', 8.5)
    $bar = New-Object Windows.Forms.Panel; $bar.Location = New-Object Drawing.Point(12, 50); $bar.Size = New-Object Drawing.Size(636, 8); $bar.BackColor = $Track
    $fill = New-Object Windows.Forms.Panel; $fill.Dock = 'Left'; $fill.Width = 0; $fill.BackColor = $Orange; $bar.Controls.Add($fill)
    $st = New-Label '' 12 59 636 18 $Dim $font; $st.Font = New-Object Drawing.Font('Segoe UI', 9)
    if ($err) { $st.Text = $err; $st.ForeColor = $Red } else { $st.Text = T 'ready' }
    $x = New-Label ([string][char]0x00D7) 628 4 24 24 $Dim $fontB; $x.Cursor = 'Hand'
    $p.Controls.AddRange(@($tl, $fl, $bar, $st, $x))
    $it = @{ path = $path; ok = ($err -eq ''); game = $info.game; serial = $info.serial; panel = $p; bar = $bar; fill = $fill; st = $st; tl = $tl; state = 'ready' }
    $x.Tag = $it
    $x.Add_Click({ param($s, $e) if (-not $script:running) { $i = $s.Tag; $cards.Controls.Remove($i.panel); $script:items.Remove($i); Relayout } })
    [void]$script:items.Add($it); $cards.Controls.Add($p); Relayout
    $result.Text = ''; $result.ForeColor = $Fg
}
function Add-Paths($paths) { foreach ($p in $paths) { Add-Iso $p } }

$onEnter = { param($s, $e) if ($e.Data.GetDataPresent([Windows.Forms.DataFormats]::FileDrop)) { $e.Effect = 'Copy' } else { $e.Effect = 'None' } }
$onDrop = { param($s, $e) Add-Paths ($e.Data.GetData([Windows.Forms.DataFormats]::FileDrop)) }
foreach ($c in @($form, $drop, $cards, $dropLbl)) { $c.AllowDrop = $true; $c.Add_DragEnter($onEnter); $c.Add_DragDrop($onDrop) }
$browse.Add_Click({
    $d = New-Object Windows.Forms.OpenFileDialog; $d.Filter = 'ISO (*.iso)|*.iso|*.*|*.*'; $d.Multiselect = $true; $d.Title = T 'sel_title'
    if ($d.ShowDialog() -eq 'OK') { Add-Paths $d.FileNames }
})
$dropLbl.Add_Click({ $browse.PerformClick() })

# ---------- network buttons ----------
$findBtn.Add_Click({
    $netLbl.ForeColor = $Dim; $netLbl.Text = T 'finding'; $form.Cursor = 'WaitCursor'; $form.Refresh()
    $ip = Find-Ps5; $form.Cursor = 'Default'
    if ($ip) { $ipBox.Text = $ip; $netLbl.ForeColor = $Green; $netLbl.Text = (T 'found') + $ip; Save-Ip $ip }
    else { $netLbl.ForeColor = $Red; $netLbl.Text = T 'notfound' }
})
$testBtn.Add_Click({
    $ip = $ipBox.Text.Trim()
    if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { $netLbl.ForeColor = $Red; $netLbl.Text = T 'badip'; return }
    $form.Cursor = 'WaitCursor'; $form.Refresh(); $ok = Test-Ps5 $ip; $form.Cursor = 'Default'
    if ($ok) { $netLbl.ForeColor = $Green; $netLbl.Text = T 'okconn'; Save-Ip $ip } else { $netLbl.ForeColor = $Red; $netLbl.Text = T 'badconn' }
})

# ---------- run queue ----------
$script:cur = $null; $script:proc = $null; $script:py = $null; $script:engine = $null; $script:cancelled = $false; $script:log = @()
$timer = New-Object Windows.Forms.Timer; $timer.Interval = 100

function Format-Eta([int]$s) { if ($s -lt 0) { return '' }; if ($s -ge 3600) { return ('{0}:{1:00}:{2:00}' -f [int][Math]::Floor($s / 3600), [int][Math]::Floor(($s % 3600) / 60), ($s % 60)) }; '{0}:{1:00}' -f [int][Math]::Floor($s / 60), ($s % 60) }
function Format-Speed([double]$b) { if ($b -ge 1MB) { '{0:N1} MB/s' -f ($b / 1MB) } elseif ($b -gt 0) { '{0:N0} KB/s' -f ($b / 1KB) } else { '' } }
function Apply-Line($it, $o) {
    $ph = [string]$o.phase; $key = "phase_$ph"
    $txt = if ($S.ContainsKey($key)) { T $key } else { $ph }
    $parts = @($txt, ('{0}%' -f [int]$o.percent))
    $sp = Format-Speed ([double]$o.speed_bps); if ($sp) { $parts += $sp }
    if ($o.eta_s -ge 0 -and $ph -notin 'done', 'failed') { $e = Format-Eta ([int]$o.eta_s); if ($e) { $parts += "$e " + (T 'left') } }
    $it.st.ForeColor = $Dim; $it.st.Text = ($parts -join '   |   ')
    if ($o.message -and $ph -ne 'done') { $it.st.Text += '   |   ' + $o.message }
    $script:lastMsg = [string]$o.message
    Set-Bar $it ([int]$o.overall)
}
function Update-All {
    $n = [Math]::Max(1, @($script:queueAll).Count); $sum = 0
    foreach ($it in $script:queueAll) { if ($it.state -eq 'done') { $sum += 100 } elseif ($it.state -eq 'running') { $sum += [int]($it.fill.Width * 100 / [Math]::Max(1, $it.bar.Width)) } }
    $allFill.Width = [int]($allBar.Width * ($sum / $n) / 100)
}
function Fail-Hint([string]$msg) {
    $m = $msg.ToLower()
    if ($m -match 'connect|refused|timed? ?out|unreachable|no route|reset') { return T 'hint_conn' }
    if ($m -match 'space|disk|full') { return T 'hint_space' }
    if ($m -match 'iso|disc|serial|unknown|checksum|corrupt') { return T 'hint_disc' }
    T 'hint_any'
}
function Finish-All {
    $timer.Stop(); $script:running = $false; $startBtn.Enabled = $true; $cancelBtn.Enabled = $false
    $okc = @($script:queueAll | Where-Object { $_.state -eq 'done' }).Count; $tot = @($script:queueAll).Count
    if ($script:cancelled) { $result.ForeColor = $Dim; $result.Text = T 'cancelled' }
    elseif ($okc -eq $tot) { $result.ForeColor = $Green; $result.Text = T 'success' }
    else {
        $bad = $script:queueAll | Where-Object { $_.state -eq 'failed' } | Select-Object -First 1
        $result.ForeColor = $Red
        $result.Text = $(if ($okc -gt 0) { T 'partial' } else { T 'failed' }) + "`n" + (Fail-Hint $bad.reason)
    }
    if ($ScreenshotTo) { $form.Refresh(); $bmp = New-Object Drawing.Bitmap($form.Width, $form.Height); $form.DrawToBitmap($bmp, (New-Object Drawing.Rectangle(0, 0, $bmp.Width, $bmp.Height))); $bmp.Save($ScreenshotTo); $form.Close() }
}
function Start-Next {
    $next = $script:queueAll | Where-Object { $_.state -eq 'ready' } | Select-Object -First 1
    if (-not $next -or $script:cancelled) { Finish-All; return }
    $script:cur = $next; $next.state = 'running'; $next.st.Text = T 'phase_detect'; $script:log = @(); $script:lastMsg = ''
    $tools = Join-Path $Home5 'tools'
    $a = @($script:py[1]) + @('-u', ('"{0}"' -f $script:engine), '--game', $next.game, '--iso', ('"{0}"' -f $next.path), '--ps5', $script:ip, '--port', $Port, '--tools-dir', ('"{0}"' -f $tools), '--json-progress')
    try { $script:proc = [OgProc]::Start($script:py[0], ($a -join ' ')) }
    catch { $next.state = 'failed'; $next.reason = "$_"; $next.st.ForeColor = $Red; $next.st.Text = (T 'failed') + ': ' + $_; Start-Next }
}
$timer.Add_Tick({
    if (-not $script:proc) { return }
    $line = $null
    while ($script:proc.Out.TryDequeue([ref]$line)) {
        $o = $null
        if ($line -match '^\s*\{') { try { $o = $line | ConvertFrom-Json } catch { } }
        if ($o -and $o.phase) { Apply-Line $script:cur $o } elseif ($line) { $script:log += $line; if ($script:log.Count -gt 20) { $script:log = $script:log[-20..-1] } }
    }
    if ($script:proc.P.HasExited) {
        $script:proc.P.WaitForExit()
        while ($script:proc.Out.TryDequeue([ref]$line)) { if ($line -match '^\s*\{') { try { Apply-Line $script:cur ($line | ConvertFrom-Json) } catch { } } else { $script:log += $line } }
        $it = $script:cur; $code = $script:proc.P.ExitCode; $script:proc = $null
        if ($script:cancelled) { $it.state = 'cancelled'; $it.st.Text = T 'cancelled' }
        elseif ($code -eq 0) { $it.state = 'done'; Set-Bar $it 100; $it.st.ForeColor = $Green; $it.st.Text = T 'done' }
        else {
            $it.state = 'failed'; $why = $script:lastMsg; if (-not $why -and $script:log.Count) { $why = $script:log[-1] }
            $it.reason = "$why"; $it.fill.BackColor = $Red; $it.st.ForeColor = $Red; $it.st.Text = (T 'failed') + ': ' + $why
        }
        Update-All; Start-Next
    } else { Update-All }
})

$startBtn.Add_Click({
    $ip = $ipBox.Text.Trim()
    $ready = @($script:items | Where-Object { $_.ok -and $_.state -in 'ready', 'failed', 'cancelled' })
    if ($ready.Count -eq 0) { $result.ForeColor = $Red; $result.Text = T 'nogames'; return }
    if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { $findBtn.PerformClick(); $ip = $ipBox.Text.Trim(); if (-not $ip) { return } }
    $script:engine = Find-Engine
    if (-not $script:engine) { $result.ForeColor = $Red; $result.Text = T 'noengine'; return }
    $script:py = Find-Python
    if (-not $script:py) {
        if (-not (Install-Python)) { $result.ForeColor = $Red; $result.Text = (T 'nopy') + "`n" + (T 'pyfail'); return }
        $script:py = Find-Python
        if (-not $script:py) { $result.ForeColor = $Red; $result.Text = T 'pyfail'; return }
    }
    Save-Ip $ip; $script:ip = $ip; $script:cancelled = $false; $script:running = $true
    foreach ($it in $ready) { $it.state = 'ready'; $it.fill.BackColor = $Orange; Set-Bar $it 0; $it.st.ForeColor = $Dim; $it.st.Text = T 'waiting' }
    $script:queueAll = $ready; $result.Text = ''; $allFill.Width = 0
    $startBtn.Enabled = $false; $cancelBtn.Enabled = $true; $timer.Start(); Start-Next
})
$cancelBtn.Add_Click({
    $script:cancelled = $true
    if ($script:proc) { try { & taskkill /T /F /PID $script:proc.P.Id 2>&1 | Out-Null } catch { } }
    $cancelBtn.Enabled = $false
})
$form.Add_FormClosing({ if ($script:proc -and -not $script:proc.P.HasExited) { try { & taskkill /T /F /PID $script:proc.P.Id 2>&1 | Out-Null } catch { } } })

# ---------- startup ----------
$cfg = Load-Cfg
if ($Ps5) { $ipBox.Text = $Ps5 } elseif ($cfg -and $cfg.ps5) { $ipBox.Text = [string]$cfg.ps5 }
$form.Add_Shown({
    # update check: the newest release's tiny VERSION asset against the VERSION file shipped with this window; silent on any problem
    try {
        $script:haveVer = (Get-Content (Join-Path $PSScriptRoot '..\..\VERSION') -TotalCount 1).Trim()
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $script:updTask = (New-Object Net.WebClient).DownloadStringTaskAsync($(if ($env:OGPS5_BASE) { $env:OGPS5_BASE } else { 'https://github.com/0iy/opengoal-ps5/releases/latest/download' }) + '/VERSION')
        $updTimer = New-Object Windows.Forms.Timer; $updTimer.Interval = 500
        $updTimer.Add_Tick({
            param($tm, $ev)  # not $s: PowerShell names are case-insensitive and $S is the text table used by T
            if (-not $script:updTask.IsCompleted) { return }
            $tm.Stop()
            try {
                $new = $script:updTask.Result.Trim()
                if ($new -match '^\d+(\.\d+){1,3}$' -and ([version]$new) -gt ([version]$script:haveVer)) { $updLbl.Text = (T 'upd') -f $new, $script:haveVer }
                if ($env:OGPS5_UPD_SHOT) { $form.Refresh(); $bmp = New-Object Drawing.Bitmap($form.Width, $form.Height); $form.DrawToBitmap($bmp, (New-Object Drawing.Rectangle(0, 0, $bmp.Width, $bmp.Height))); $bmp.Save($env:OGPS5_UPD_SHOT); $form.Close() }  # test hook
            } catch { }
        })
        $updTimer.Start()
    } catch { }
    Add-Paths $Iso
    if (-not $ipBox.Text -and -not $AutoStart) { $findBtn.PerformClick() }
    if ($AutoStart) { $startBtn.PerformClick() }
})
[Windows.Forms.Application]::add_ThreadException({
    param($s, $e)
    try { New-Item -ItemType Directory -Force $Home5 | Out-Null; "$([DateTime]::Now) $($e.Exception)" | Add-Content (Join-Path $Home5 'gui.log') } catch { }
    [Console]::Error.WriteLine("GUI error: $($e.Exception.Message)")
    $result.ForeColor = $Red; $result.Text = "Internal error: $($e.Exception.Message)"
})
[void]$form.ShowDialog()
