# -*- coding: utf-8 -*-
"""User-initiated self-update via the GitHub Releases API. Standard library only.

Design constraints (project-specific):
  * The portable EXE is UNSIGNED and already triggers Defender 'Wacatac'
    false-positives. Therefore the update is STRICTLY user-initiated: we only
    CHECK on startup (in a background thread) and show a dismissible banner. We
    NEVER auto-download or auto-run. The download + self-replace happen only
    after an explicit click on "Jetzt aktualisieren".
  * Must never block or crash the UI. Every public function is wrapped so a
    missing network / API error / parse error silently degrades to "no update".
  * Self-replace only for the ONEFILE portable build (frozen AND ``sys._MEIPASS``
    present). Source/onedir -> open the releases page instead (overwriting only
    a onedir stub ``sys.executable`` would corrupt the install).

Public surface (used by interface.app):
  * ``check_for_update`` / ``start_background_check`` -- non-blocking version check
  * ``download_asset`` -- streamed download with progress + sanity check
  * ``apply_update_onefile`` -- write+launch the self-replace helper .bat
  * ``open_releases_page`` -- browser fallback for source/onedir
  * ``is_frozen`` / ``is_onefile`` / ``is_onedir`` / ``can_self_replace``
  * ``UpdateInfo`` (carrier) and ``UpdateError`` (failure)
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
import webbrowser
from collections import namedtuple

from version import __version__, version_tuple


# -- constants --------------------------------------------------------------

GITHUB_API_LATEST = (
    'https://api.github.com/repos/DartagnanXE/Metin2MultiTool/releases/latest')
RELEASES_PAGE = 'https://github.com/DartagnanXE/Metin2MultiTool/releases/latest'
PORTABLE_ASSET_NAME = 'Metin2MultiTool-Portable.exe'
HTTP_TIMEOUT = 6              # seconds; short so a hang never stalls anything
MIN_ASSET_BYTES = 2_000_000   # sanity floor (the real exe is tens of MB)
_USER_AGENT = 'Metin2MultiTool-Updater'
_CHUNK = 64 * 1024

# Hosts the portable EXE may be downloaded from. A GitHub release asset's
# ``browser_download_url`` points at github.com and 302-redirects to
# objects.githubusercontent.com (sometimes release-assets.githubusercontent.com).
# The downloaded bytes are LAUNCHED as an EXE, so we pin the download to these
# GitHub hosts: a tampered/spoofed API response (MitM, DNS poisoning) cannot then
# steer the download to an attacker-controlled URL.
_ALLOWED_UPDATE_HOSTS = frozenset({
    'github.com',
    'objects.githubusercontent.com',
    'release-assets.githubusercontent.com',
})


def _validate_download_url(url):
    """Reject a download URL that is not HTTPS to a trusted GitHub host.

    Raises :class:`UpdateError` (``'insecure_url'`` / ``'untrusted_host'``) so the
    caller's existing failure path handles it; the host comparison is
    case-insensitive and ignores any ``user:pass@``/port portion.
    """
    from urllib.parse import urlsplit
    parts = urlsplit(url or '')
    if parts.scheme != 'https':
        raise UpdateError('insecure_url')
    host = (parts.hostname or '').lower()
    if host not in _ALLOWED_UPDATE_HOSTS:
        raise UpdateError('untrusted_host')


class UpdateError(Exception):
    """Failure during download/apply. ``args[0]`` is a short machine code
    (e.g. ``'download_failed'``) that the UI maps to a bilingual ``t()`` key."""


# Tiny immutable carrier for one available update.
#   version:      str   normalized tag, leading 'v' stripped (e.g. '1.0.4')
#   tag:          str   raw tag as published (e.g. 'v1.0.4')
#   download_url: str|None  portable asset browser_download_url (None if absent)
#   size:         int|None  asset size in bytes from the API (sanity check)
#   page_url:     str   release html_url (fallback for onedir/source)
UpdateInfo = namedtuple('UpdateInfo',
                        ['version', 'tag', 'download_url', 'size', 'page_url'])


# -- build-mode detection ---------------------------------------------------

def is_frozen():
    """True when running from a PyInstaller-built EXE (onefile OR onedir)."""
    return bool(getattr(sys, 'frozen', False))


def is_onefile():
    """True ONLY for the --onefile portable build.

    The onefile bootloader unpacks to a temp dir exposed as ``sys._MEIPASS``;
    the onedir build sets ``frozen`` but has NO ``_MEIPASS``. That presence is
    exactly the discriminator the project requires (mirrors respath.py).
    """
    return is_frozen() and hasattr(sys, '_MEIPASS')


def is_onedir():
    """True for the installed --onedir build (frozen, no ``_MEIPASS``)."""
    return is_frozen() and not hasattr(sys, '_MEIPASS')


def can_self_replace():
    """Only the onefile portable may overwrite its own ``sys.executable``."""
    return is_onefile()


# -- version check (runs in a background thread) ----------------------------

def fetch_latest_release(timeout=HTTP_TIMEOUT):
    """GET the latest-release JSON. Returns a dict or ``None`` (never raises).

    A ``User-Agent`` header is REQUIRED by the GitHub API (it rejects requests
    without one with HTTP 403). HTTPS only, no token -- one unauthenticated call
    per startup is far under the 60 req/hr limit.
    """
    try:
        req = urllib.request.Request(
            GITHUB_API_LATEST,
            headers={'User-Agent': _USER_AGENT,
                     'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, 'status', 200) not in (200, None):
                return None
            raw = resp.read()
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return None


def parse_release(data):
    """Turn the release dict into an :class:`UpdateInfo` (or ``None``).

    Picks the asset whose ``name`` equals :data:`PORTABLE_ASSET_NAME` and takes
    its ``browser_download_url`` + ``size``. Never raises.
    """
    try:
        if not isinstance(data, dict):
            return None
        tag = str(data.get('tag_name') or '').strip()
        if not tag:
            return None
        page = str(data.get('html_url') or RELEASES_PAGE)
        url, size = None, None
        for asset in (data.get('assets') or []):
            try:
                if asset.get('name') == PORTABLE_ASSET_NAME:
                    url = asset.get('browser_download_url')
                    size = asset.get('size')
                    break
            except AttributeError:
                continue
        normalized = '.'.join(str(p) for p in version_tuple(tag))
        return UpdateInfo(version=normalized, tag=tag,
                          download_url=url, size=size, page_url=page)
    except Exception:
        return None


def check_for_update(current=__version__, timeout=HTTP_TIMEOUT):
    """Full check. Returns an :class:`UpdateInfo` IF the latest release is
    strictly newer than ``current`` (version-tuple compare), else ``None``.
    Never raises. This is what the background thread calls.
    """
    try:
        data = fetch_latest_release(timeout=timeout)
        if data is None:
            return None
        info = parse_release(data)
        if info is None:
            return None
        if version_tuple(info.tag) > version_tuple(current):
            return info
        return None
    except Exception:
        return None


def start_background_check(on_update_available, current=__version__):
    """Spawn a daemon thread that runs :func:`check_for_update` and, IF a newer
    version exists, calls ``on_update_available(update_info)``.

    The callback runs on the WORKER thread -> the UI layer MUST marshal back
    onto the GUI thread (``app.after(0, ...)``). Returns the started ``Thread``.
    Never raises; on any failure the thread simply exits (no banner).
    """
    def _worker():
        try:
            info = check_for_update(current=current)
            if info is not None and callable(on_update_available):
                on_update_available(info)
        except Exception:
            pass   # a background check must never surface an error

    try:
        thread = threading.Thread(target=_worker, name='update-check',
                                  daemon=True)
        thread.start()
        return thread
    except Exception:
        return None


# -- download + self-replace ------------------------------------------------

def _safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def download_asset(update_info, dest_dir=None, progress=None):
    """Stream the portable asset to ``<dest_dir or %TEMP%>``.

    Downloads to ``*.part`` then atomically renames into
    ``Metin2FishBot-Portable-<version>.exe`` so a half file never appears under
    the final name. Calls ``progress(done_bytes, total_bytes)`` if given (total
    may be ``None``). Sanity-checks the final size against :data:`MIN_ASSET_BYTES`
    and (when known) the API-reported size. Returns the destination path on
    success; raises :class:`UpdateError` on failure (the caller catches).
    """
    url = getattr(update_info, 'download_url', None)
    if not url:
        raise UpdateError('no_asset')
    # Pin the download to trusted GitHub hosts before opening the connection: the
    # downloaded bytes are launched as an EXE, so a spoofed API response must not
    # be able to point us at an attacker-controlled URL.
    _validate_download_url(url)
    dest_dir = dest_dir or tempfile.gettempdir()
    version = getattr(update_info, 'version', '0') or '0'
    dest = os.path.join(dest_dir,
                        'Metin2FishBot-Portable-{}.exe'.format(version))
    tmp = dest + '.part'
    try:
        # browser_download_url 302-redirects to objects.githubusercontent.com;
        # urllib follows redirects by default, so no extra handling is needed.
        req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            try:
                total = int(resp.headers.get('Content-Length') or 0) or None
            except Exception:
                total = None
            done = 0
            with open(tmp, 'wb') as out:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if callable(progress):
                        try:
                            progress(done, total)
                        except Exception:
                            pass
        if done < MIN_ASSET_BYTES:
            _safe_remove(tmp)
            raise UpdateError('too_small')
        expected = getattr(update_info, 'size', None)
        if expected and abs(done - int(expected)) > 1024:
            _safe_remove(tmp)
            raise UpdateError('size_mismatch')
        os.replace(tmp, dest)   # atomic rename into the final name
        return dest
    except UpdateError:
        raise
    except Exception as exc:
        _safe_remove(tmp)
        raise UpdateError('download_failed') from exc


# Self-replace helper .bat. NOTE: ``str.format`` only treats ``{`` / ``}`` as
# special -- it leaves ``%`` untouched -- so cmd variables stay SINGLE ``%VAR%``
# (doubling to ``%%`` would NOT expand the var outside a FOR loop and is wrong
# here). Only {pid}/{target}/{new} are substituted. The literal paths we inject
# never contain ``{``/``}``, so no brace-escaping is needed. Written with CRLF +
# ascii (see apply_update_onefile).
_BAT_TEMPLATE = '''@echo off
setlocal enableextensions
rem --- Metin2FishBot self-update helper (generated; safe to delete) -------
rem Values are baked in by updater.py: PID, target exe, freshly downloaded exe.
rem Laeuft windowless (CREATE_NO_WINDOW); ALLE Schleifen sind HART BEGRENZT,
rem damit der Helfer nie endlos weiterlaeuft (frueherer Bug: Fenster-Flut +
rem nicht beendbar, wenn die alte PID nicht starb).
set "PID=@@PID@@"
set "TARGET=@@TARGET@@"
set "NEW=@@NEW@@"
set "N=0"

rem 1) Warte (max ~60s) bis DIESE App (per PID) beendet ist -> exe entsperrt.
:waitloop
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if errorlevel 1 goto copyloop
set /a N+=1
if %N% GEQ 60 goto copyloop
ping -n 2 127.0.0.1 >nul
goto waitloop

rem 2) Datei-Handle freigeben lassen, dann drueberkopieren (max ~60 Versuche).
:copyloop
ping -n 2 127.0.0.1 >nul
copy /Y "%NEW%" "%TARGET%" >nul
if not errorlevel 1 goto relaunch
set /a N+=1
if %N% GEQ 120 goto relaunch
goto copyloop

rem 3) Aktualisierte App neu starten, Download aufraeumen, selbst loeschen.
:relaunch
start "" "%TARGET%"
del /Q "%NEW%" >nul 2>&1
del /Q "%~f0" >nul 2>&1
'''


def build_update_bat(pid, target, new):
    """Return the literal .bat text for the self-replace helper.

    Substitution uses ``str.replace`` on ``@@...@@`` sentinels (NOT ``.format``):
    this leaves every cmd ``%VAR%`` as a SINGLE ``%`` and is immune to a ``{``,
    ``}`` or ``%`` ever appearing in an injected path. Pure string builder (no
    I/O, no process launch) so it is trivially unit-testable: the result must
    contain the PID, the target exe path, the downloaded path and the loop labels.
    """
    return (_BAT_TEMPLATE
            .replace('@@PID@@', str(pid))
            .replace('@@TARGET@@', str(target))
            .replace('@@NEW@@', str(new)))


def apply_update_onefile(downloaded_path):
    """Write the helper .bat to ``%TEMP%``, launch it DETACHED, and return its
    path. The CALLER must then exit the app so the exe handle is released and
    the .bat's ``copy /Y`` can succeed.

    ONLY valid for the onefile portable (asserted via :func:`can_self_replace`).
    Raises :class:`UpdateError` on failure.
    """
    if not can_self_replace():
        raise UpdateError('not_onefile')
    if not downloaded_path or not os.path.exists(downloaded_path):
        raise UpdateError('download_missing')
    target = sys.executable   # in onefile this is the REAL portable .exe path
    pid = os.getpid()
    bat = build_update_bat(pid=pid, target=target, new=downloaded_path)
    bat_path = os.path.join(tempfile.gettempdir(),
                            'Metin2FishBot-update-{}.bat'.format(pid))
    try:
        with open(bat_path, 'w', encoding='ascii', newline='\r\n') as handle:
            handle.write(bat)
    except Exception as exc:
        raise UpdateError('helper_write_failed') from exc
    try:
        _launch_detached(bat_path)
    except Exception as exc:
        raise UpdateError('helper_launch_failed') from exc
    return bat_path


def _launch_detached(bat_path):
    """Start the helper .bat windowless + surviving our exit.

    KRITISCH (Bug-Fix): NUR ``CREATE_NO_WINDOW`` -- NICHT ``DETACHED_PROCESS``.
    ``DETACHED_PROCESS`` gibt dem ``cmd`` GAR KEINE Konsole, woraufhin jeder
    Kindbefehl (``tasklist``/``find``/``ping``) sich eine EIGENE SICHTBARE Konsole
    allokiert -> beim Update ploppten Dutzende CMD-Fenster auf (unbeendbar).
    ``CREATE_NO_WINDOW`` gibt dem ``cmd`` eine VERSTECKTE Konsole, die die Kinder
    erben -> kein einziges Fenster. Der Prozess ueberlebt unseren Exit ohnehin
    (Popen bindet die Lebensdauer nicht). ``CREATE_NEW_PROCESS_GROUP`` entkoppelt
    von Ctrl+C. App elevated -> Kind erbt Elevation (relaunch bleibt elevated).
    """
    new_group = 0x00000200         # CREATE_NEW_PROCESS_GROUP
    no_window = 0x08000000         # CREATE_NO_WINDOW (versteckte Konsole, vererbt)
    # Doppelte Absicherung (bombenfest): zusaetzlich STARTUPINFO mit SW_HIDE,
    # falls eine exotische Windows-/AV-Konfig CREATE_NO_WINDOW ignorieren wuerde.
    # STARTUPINFO existiert nur unter Windows -> defensiv (None sonst).
    startupinfo = None
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0          # SW_HIDE
    except Exception:
        startupinfo = None
    subprocess.Popen(
        ['cmd', '/c', bat_path],
        creationflags=new_group | no_window,
        startupinfo=startupinfo,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)


def open_releases_page(url=RELEASES_PAGE):
    """Open the releases page in the default browser. Never raises.

    Used for the source/onedir path (where self-replace is unsafe) and as a
    fallback when a onefile release has no portable asset.
    """
    try:
        webbrowser.open(url or RELEASES_PAGE)
        return True
    except Exception:
        return False
