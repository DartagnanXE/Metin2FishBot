# -*- coding: utf-8 -*-
"""Ranking telemetry package (OPT-IN, GDPR-gated).

Import surface mirrors ``interface/__init__``: the PURE pieces (``hwid``,
``payload``) import with stdlib only, so headless tests can use them WITHOUT
pulling in threads/network. The IO ``client`` (urllib + daemon thread) is
exposed lazily via ``__getattr__`` so merely importing :mod:`telemetry` never
starts a thread or touches the network.

GDPR / opt-in gate (load-bearing on a public repo with a German user):
  * Telemetry is OFF until the user explicitly opts in (config
    ``telemetry.enabled`` is False by default and the first-run onboarding
    checkbox defaults OFF).
  * The ONLY personal datum is the self-chosen username. The HWID is a hashed,
    spoofable machine id used purely so the server can ban/delete abusers.
  * Nothing is sent while disabled or while the username is empty (see
    ``client.start_sender``).
"""

from telemetry import hwid, payload   # pure, stdlib-only

__all__ = ['hwid', 'payload', 'client']


def __getattr__(name):
    """Lazily import the network ``client`` only when actually accessed.

    Keeps ``import telemetry`` (and the pure tests) free of urllib/threads.
    Uses ``importlib`` (NOT ``from telemetry import client``) so this hook does
    not recurse into itself.
    """
    if name == 'client':
        import importlib
        return importlib.import_module('telemetry.client')
    raise AttributeError(
        '{!r} has no attribute {!r}'.format(__name__, name))
