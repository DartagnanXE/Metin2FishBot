# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Spec fuer den Metin2 Fishing Bot.
#
# Ziel: "best possible" gegen die generische Heuristik-Erkennung (Wacatac/
# Wacapew/Sabsik). Massnahmen in dieser Spec:
#   * upx=False           -> KEIN UPX-Packing. UPX-komprimierte PyInstaller-EXEs
#                            sind ein Haupt-Trigger fuer Heuristik-Flags.
#   * --onedir (COLLECT)  -> KEIN selbstentpackender --onefile-Stub mehr. Der
#                            Self-Extractor (sys._MEIPASS in %TEMP%) ist das
#                            verdaechtigste Verhaltensmuster. onedir legt alles
#                            offen neben die EXE -> deutlich weniger FP.
#   * version=...         -> echte PE-Versions-Ressource (Firmenname, Produkt,
#                            Version, Copyright). Unsignierte EXEs OHNE Metadaten
#                            werden besonders gern geflaggt.
#   * console=False       -> kein stoerendes leeres CMD-Fenster.
#
# Assets (images/, pieces_second.json, fishs.txt) bleiben eingebettet; respath
# loest die Pfade in beiden Welten (Quellcode + gepackt) korrekt auf.
#
# Build:  pyinstaller --clean --noconfirm Metin2FishBot.spec
#         -> erzeugt dist/Metin2FishBot/ (Ordner mit Metin2FishBot.exe + Libs)
# Hinweis: Ausgeliefert wird die Portable (Metin2FishBot_onefile.spec, was auch
# build.bat baut). Diese onedir-Spec bleibt als Entwickler-/Fallback-Build.

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
    StringStruct, VarFileInfo, VarStruct,
)

block_cipher = None

# --- Versions-Konstanten: EINE Quelle der Wahrheit ist version.py (Repo-Root).
# SPEC ist der absolute Pfad dieser Spec (von PyInstaller injiziert) -> dessen
# Verzeichnis ist das Repo-Root, wo version.py liegt; robust unabhaengig vom cwd.
# Beide Specs importieren __version__ aus version.py -> beim Release nur dort
# bumpen (keine manuelle Synchronisierung mehr noetig).
sys.path.insert(0, os.path.dirname(os.path.abspath(SPEC)))
from version import __version__, version_tuple

APP_NAME = 'Metin2FishBot'
APP_VERSION = __version__                     # aus version.py (__version__)
APP_PUBLISHER = 'Musketier Software'
APP_COPYRIGHT = ''   # bewusst ohne Copyright-Vermerk
# PE-Ressource braucht ein 4-stelliges Int-Tupel -> aus __version__ ableiten,
# rechts mit Nullen auf 4 Felder auffuellen.
_vt = version_tuple(__version__)
_VTUPLE = tuple((list(_vt) + [0, 0, 0, 0])[:4])  # 4-stellig fuer die PE-Ressource

# Optionales App-Icon: liegt 'musketier.ico' neben dieser Spec, wird es ins EXE
# eingebettet (erscheint dann ueberall als Programm-Icon -- Taskleiste,
# Verknuepfungen, Apps & Features); sonst PyInstaller-Standard-Icon.
APP_ICON = 'musketier.ico' if os.path.exists('musketier.ico') else None

# CustomTkinter bringt eigene Theme-/Asset-Dateien (.json/.otf) mit, die ohne
# explizites Sammeln in der gepackten App fehlen wuerden -> CTk startet sonst
# nicht. Darkdetect (CTk-Dependency) als Submodule mitnehmen.
ctk_datas = collect_data_files('customtkinter')
ctk_hidden = collect_submodules('customtkinter') + ['darkdetect']

# --- PE-Versions-Ressource (zeigt Windows echte Datei-Eigenschaften an) ------
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_VTUPLE,
        prodvers=_VTUPLE,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,        # VOS_NT_WINDOWS32
        fileType=0x1,      # VFT_APP
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable(
                '040704B0',  # German (Germany), Unicode codepage
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
        ('images', 'images'),               # alle Template-Bilder
        ('pieces_second.json', '.'),        # Eroeffnungsbuch
        ('fishs.txt', '.'),                 # Fischnamen-Liste (Angeln)
    ] + ctk_datas + ([(APP_ICON, '.')] if APP_ICON else []),  # Icon als Laufzeit-Datei (Fenster-Icon)
    hiddenimports=[
        'win32gui', 'win32ui', 'win32con',  # pywin32 (windowcapture)
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
    excludes=[
        'FreeSimpleGUI',  # altes Toolkit ist raus -> nicht mehr bundeln
        'PySimpleGUI',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --- onedir: EXE-Stub OHNE eingebettete Binaries (exclude_binaries=True) ------
exe = EXE(
    pyz,
    a.scripts,
    [],                       # KEINE a.binaries/zipfiles/datas hier -> COLLECT
    exclude_binaries=True,    # <-- das macht aus --onefile ein --onedir
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # <-- KEIN UPX (Haupt-FP-Trigger)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # kein leeres Konsolenfenster
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_info,     # <-- echte PE-Metadaten
    icon=APP_ICON,            # <-- Programm-Icon (musketier.ico), falls vorhanden
    uac_admin=True,           # EXE fordert automatisch Admin an (UAC) -- noetig fuer
                              # Input-Zustellung ans (meist erhoehte) Spiel (UIPI).
)

# --- COLLECT: legt EXE + alle Libs/Assets als Ordner dist/Metin2FishBot/ ab --
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,                # auch hier kein UPX
    upx_exclude=[],
    name=APP_NAME,
)
