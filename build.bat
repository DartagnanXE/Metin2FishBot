@echo off
REM ===================================================================
REM  Metin2 Fishing Bot - Build (Doppelklick genuegt)
REM
REM  1) Abhaengigkeiten installieren (gepinnte requirements.txt)
REM  2) PyInstaller-Build -> dist_onefile\Metin2FishBot.exe
REM     (Portable, EINE Datei; --onefile, upx=False, PE-Metadaten;
REM      siehe Metin2FishBot_onefile.spec)
REM
REM  Ergebnis: EINE portable Metin2FishBot.exe zum Weitergeben (Doppelklick,
REM  keine Installation).
REM ===================================================================
cd /d "%~dp0"
echo === Metin2 Fishing Bot: Build (Portable, eine EXE) ===

REM Python finden (py-Launcher bevorzugt, sonst python)
where py >nul 2>nul && (set "PY=py") || (set "PY=python")

echo [1/3] Abhaengigkeiten installieren (robust ueber Python 3.11-3.13)
%PY% -m pip install --upgrade pip >nul 2>nul
%PY% -m pip install --prefer-binary -r requirements.txt || goto :err

echo [2/3] Alte Build-Artefakte aufraeumen
if exist build rmdir /s /q build
if exist dist_onefile rmdir /s /q dist_onefile

echo [3/3] PyInstaller-Build (Portable, --onefile, upx=False, PE-Metadaten)
%PY% -m PyInstaller --clean --noconfirm --distpath dist_onefile Metin2FishBot_onefile.spec || goto :err

if not exist "dist_onefile\Metin2FishBot.exe" (
    echo *** FEHLER: dist_onefile\Metin2FishBot.exe wurde nicht erzeugt.
    goto :err
)

echo.
echo FERTIG. Portable liegt hier:  dist_onefile\Metin2FishBot.exe
echo Diese EINE Datei an die Nutzer weitergeben (Doppelklick, keine Installation).
echo (Als Admin starten. Spiel in 800x600, nicht Vollbild.)
echo Diagnose landet in:  puzzle_debug.log  (neben der EXE)

echo.
pause
exit /b 0

:err
echo.
echo *** FEHLER beim Build. Bitte die Ausgabe oben pruefen. ***
echo Haeufige Ursache: Python 3.11-3.13 (64-bit) noetig. Bei Wheel-/Netzwerk-
echo Problemen:  py -m pip install --upgrade pip   und erneut starten.
pause
exit /b 1
