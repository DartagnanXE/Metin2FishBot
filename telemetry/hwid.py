# -*- coding: utf-8 -*-
"""Stable per-machine id for the ranking (PURE hashing + thin OS read).

Threat model (honest, not oversold): the client is open source, so anyone
editing it can spoof this id. The HWID is therefore NOT an authentication
token -- it is mass-protection only, so the server can ban/delete the bulk of
abusers by a stable handle. This is documented in server/THREAT_MODEL.md.

Split for testability:
  * compute_hwid(...) is PURE -- given raw inputs it returns a deterministic
    sha256 hex prefix. Unit-tested with injected values (no OS access).
  * get_hwid() reads OS sources via THIN wrappers (_read_machine_guid via
    winreg, _read_volume_serial) that return ``None`` off-Windows/headless, then
    delegates to compute_hwid. Never raises -> a deterministic fallback derived
    from the hostname keeps a stable-ish id even with no OS source.

Stdlib only (hashlib/platform/winreg-optional). No PII: only an opaque hash.
"""

import hashlib
import platform

# Truncated digest length (hex chars). 32 hex = 128 bits -> ample for a handle
# while keeping the stored value small. Mirrored by USERNAME/HWID caps server-side.
HWID_HEX_LEN = 32


def compute_hwid(raw_guid=None, raw_serial=None, node=None):
    """PURE: derive a stable hex id from machine identifiers.

    Combines the (optional) Windows MachineGuid, a volume serial and the host
    node name into a single sha256, returns the first :data:`HWID_HEX_LEN` hex
    chars. Deterministic for the same inputs; different inputs -> different id.
    If all identifiers are missing it falls back to ``'unknown-host'`` + node so
    the result is still stable per machine (honestly spoofable). Never raises.
    """
    try:
        parts = []
        parts.append(str(raw_guid) if raw_guid else '')
        parts.append(str(raw_serial) if raw_serial else '')
        if node is None:
            try:
                node = platform.node()
            except Exception:
                node = ''
        parts.append(str(node) if node else '')
        # If we have NO real machine identifier, anchor on a constant so the
        # fallback is deterministic rather than empty.
        if not (raw_guid or raw_serial):
            parts.insert(0, 'unknown-host')
        material = '|'.join(parts).encode('utf-8', 'replace')
        return hashlib.sha256(material).hexdigest()[:HWID_HEX_LEN]
    except Exception:
        # Absolute last resort -- a fixed but valid hex string.
        return hashlib.sha256(b'unknown-host').hexdigest()[:HWID_HEX_LEN]


def _read_machine_guid():
    """Read HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid (Windows only).

    Thin OS wrapper: returns the GUID string or ``None`` off-Windows / on any
    error. Never raises.
    """
    try:
        import winreg
    except Exception:
        return None
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\Microsoft\Cryptography', 0,
            winreg.KEY_READ | getattr(winreg, 'KEY_WOW64_64KEY', 0))
        try:
            value, _type = winreg.QueryValueEx(key, 'MachineGuid')
            return str(value) if value else None
        finally:
            winreg.CloseKey(key)
    except Exception:
        return None


def _read_volume_serial():
    """Read the system-drive volume serial via the Windows API (or ``None``).

    Thin OS wrapper using ctypes (Windows only); returns ``None`` off-Windows or
    on any error. Never raises.
    """
    try:
        import ctypes
    except Exception:
        return None
    try:
        kernel32 = ctypes.windll.kernel32   # AttributeError off-Windows
    except Exception:
        return None
    try:
        serial = ctypes.c_uint(0)
        ok = kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p('C:\\'), None, 0,
            ctypes.byref(serial), None, None, None, 0)
        if not ok:
            return None
        return str(serial.value)
    except Exception:
        return None


def get_hwid():
    """Compute the machine HWID from OS sources, with a stable fallback.

    Reads the MachineGuid + volume serial via the thin wrappers (both ``None``
    off-Windows) and hashes them with :func:`compute_hwid`. Never raises.
    """
    guid = _read_machine_guid()
    serial = _read_volume_serial()
    return compute_hwid(raw_guid=guid, raw_serial=serial)
