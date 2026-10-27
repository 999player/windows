# Builds dist\999player\999player.exe (one-folder app; fast startup, ~250 MB with Chromium runtime).
# Usage:  powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "`n== deps ==" -ForegroundColor Cyan
py -m pip install --upgrade pyinstaller PySide6 requests mutagen | Out-Null

Write-Host "`n== clean ==" -ForegroundColor Cyan
Get-Process -Name 999player, JuiceVault -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\build, .\dist, .\999player.spec, .\JuiceVault.spec -ErrorAction SilentlyContinue
if (-not (Test-Path .\assets\icon.ico)) { py .\make_icon.py }

Write-Host "`n== pyinstaller ==" -ForegroundColor Cyan
py -m PyInstaller --noconfirm --onedir --windowed --name "999player" `
    --icon ".\assets\icon.ico" `
    --version-file ".\assets\version_info.txt" `
    --add-data "ui;ui" `
    --add-data "assets;assets" `
    --exclude-module tkinter --exclude-module unittest --exclude-module pydoc `
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQuickWidgets `
    --exclude-module PySide6.Qt3DCore --exclude-module PySide6.Qt3DRender --exclude-module PySide6.QtCharts `
    --exclude-module PySide6.QtDataVisualization --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets `
    --exclude-module PySide6.QtBluetooth --exclude-module PySide6.QtNfc --exclude-module PySide6.QtSerialPort `
    --exclude-module PySide6.QtSensors --exclude-module PySide6.QtTest --exclude-module PySide6.QtDesigner `
    --exclude-module PySide6.QtRemoteObjects --exclude-module PySide6.QtScxml --exclude-module PySide6.QtStateMachine `
    main.py

$root = ".\dist\999player"
if (-not (Test-Path "$root\999player.exe")) { Write-Host "FAILED: no exe produced" -ForegroundColor Red; exit 1 }

Write-Host "`n== prune (keep English locale only) ==" -ForegroundColor Cyan
$loc = Get-ChildItem -Recurse -Directory "$root\_internal" -Filter "qtwebengine_locales" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($loc) { Get-ChildItem $loc.FullName -Filter "*.pak" | Where-Object { $_.Name -notin @("en-US.pak", "en-GB.pak") } | Remove-Item -Force }
$tr = Get-ChildItem -Recurse -Directory "$root\_internal" -Filter "translations" -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike "*qtwebengine_locales*" } | Select-Object -First 1
if ($tr) { Get-ChildItem $tr.FullName -File -Filter "*.qm" | Remove-Item -Force -ErrorAction SilentlyContinue }
# debug-only devtools bundle (72 MB) is never needed at runtime
Get-ChildItem -Recurse -File "$root\_internal" -Filter "qtwebengine_devtools_resources.debug.pak" | Remove-Item -Force -ErrorAction SilentlyContinue

$size = (Get-ChildItem -Recurse -File $root | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host ("`nOK -> {0}\999player.exe  (folder {1:N0} MB)" -f (Resolve-Path $root), $size) -ForegroundColor Green
