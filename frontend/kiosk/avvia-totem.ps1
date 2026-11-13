# Avvia il totem in Chrome in modalità kiosk: schermo intero senza la X per uscire (che compare
# con F11 tenendo premuto o trascinando dal bordo in alto), senza barre, schede né menu.
# La stampa non passa da Chrome: il backend manda i fogli alla stampante Bluetooth del totem.
#
# Uso:  powershell -ExecutionPolicy Bypass -File avvia-totem.ps1 [-Url http://...]
# Per uscire dal kiosk: Alt+F4.

param(
  [string]$Url = 'http://localhost:4200/'
)

$ErrorActionPreference = 'Stop'

$chrome = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw 'Chrome non trovato.' }

# Un profilo solo per il totem: se Chrome è già aperto con il profilo normale, il flag
# --kiosk verrebbe ignorato e si aprirebbe una scheda nella finestra esistente.
$profilo = Join-Path $env:LOCALAPPDATA 'TotemKiosk'

Start-Process $chrome -ArgumentList @(
  '--kiosk',
  "--user-data-dir=`"$profilo`"",
  '--no-first-run',
  '--no-default-browser-check',
  '--noerrdialogs',
  '--disable-session-crashed-bubble',
  '--disable-features=Translate',
  '--overscroll-history-navigation=0',
  '--autoplay-policy=no-user-gesture-required',
  $Url
)
