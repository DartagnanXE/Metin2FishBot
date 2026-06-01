# -*- mode: python ; coding: utf-8 -*-
# STANDALONE-Variante: EINE portable .exe (--onefile).
#
# Wie Metin2FishBot.spec, aber alles in EINE Datei gebundelt (entpackt sich
# beim Start nach %TEMP%). Bequemste Form (Doppelklick, KEINE Installation).
# Trade-off: das Self-Extract-Muster ist der groesste Ausloeser fuer generische
# Defender-Heuristik (Wacatac & Co.). Wer minimale Falsch-Positive will, nimmt
# Metin2FishBot.spec (onedir-Ordner). upx=False / PE-Metadaten / Icon bleiben.
#
# Build:  pyinstaller --clean --noconfirm --distpath dist_onefile Metin2FishBot_onefile.spec

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
    StringStruct, VarFileInfo, VarStruct,
)

block_cipher = None

# Versions-Konstanten: EINE Quelle der Wahrheit ist version.py (Repo-Root).
# SPEC ist der absolute Pfad dieser Spec (von PyInstaller injiziert) -> dessen
# Verzeichnis ist das Repo-Root, wo version.py liegt; robust unabhaengig vom cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(SPEC)))
from version import __version__, version_tuple

APP_NAME = 'Metin2FishBot'
APP_VERSION = __version__                     # aus version.py (__version__)
APP_PUBLISHER = 'Musketier Software'
APP_COPYRIGHT = ''   # bewusst ohne Copyright-Vermerk
# PE-Ressource braucht ein 4-stelliges Int-Tupel -> aus __version__ ableiten,
# rechts mit Nullen auf 4 Felder auffuellen.
_vt = version_tuple(__version__)
_VTUPLE = tuple((list(_vt) + [0, 0, 0, 0])[:4])
APP_ICON = 'musketier.ico' if os.path.exists('musketier.ico') else None

ctk_datas = collect_data_files('customtkinter')
ctk_hidden = collect_submodules('customtkinter') + ['darkdetect']

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_VTUPLE, prodvers=_VTUPLE, mask=0x3F, flags=0x0,
        OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable(
                '040704B0',
                [
                    StringStruct('CompanyName', APP_PUBLISHER),
                    StringStruct('FileDescription', 'Metin2 Fishing Bot'),
                    StringStruct('FileVersion', APP_VERSION),
                    StringStruct('InternalName', APP_NAME),
                    StringStruct('LegalCopyright', APP_COPYRIGHT),
                    StringStruct('OriginalFilename', APP_NAME + '.exe'),
                    StringStruct('ProductName', 'Metin2 Fishing Bot'),
                    StringStruct('ProductVersion', APP_VERSION),
                ],
            )
        ]),
        VarFileInfo([VarStruct('Translation', [0x0407, 1200])]),
    ],
)

a = Analysis(
    ['hack.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('images', 'images'),
        ('pieces_second.json', '.'),
        ('fishs.txt', '.'),
    ] + ctk_datas + ([(APP_ICON, '.')] if APP_ICON else []),
    hiddenimports=[
        'win32gui', 'win32ui', 'win32con',
        'pydirectinput',
        'pytesseract',
        'version', 'updater',   # lazy importiert zur Laufzeit (app.py)
        'pystray', 'PIL', 'PIL.Image', 'PIL._tkinter_finder',   # Tray + Bilder
        # Lazy in app.py-Methoden importiert (statische Analyse uebersieht sie):
        'overlay_preview', 'interface.testwindow',
        'overlay_mark', 'interface.tray',
    ] + ctk_hidden + collect_submodules('pystray'),  # pystray laedt sein Backend (pystray._win32) dynamisch -> alle Submodule mitnehmen
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['FreeSimpleGUI', 'PySimpleGUI'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --- onefile: ALLES in die EXE (a.binaries/zipfiles/datas), KEIN COLLECT ---
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # weiterhin KEIN UPX
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # kein Konsolenfenster
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_info,
    icon=APP_ICON,            # Musketier-Icon
    uac_admin=True,           # EXE fordert beim Start automatisch Admin an (UAC).
                              # Noetig, damit Tastatur/Maus das (meist als Admin
                              # laufende) Spiel erreichen -- sonst blockt Windows
                              # UIPI die Eingaben (Maus bewegt sich, Klicks/Tasten
                              # kommen nicht an). Kein "als Admin starten" mehr noetig.
)
