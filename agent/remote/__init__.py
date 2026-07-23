"""Camada RemoteSession — exporta a ABC e resolve backends sob demanda.

Neste fork: BrowserSession (+ Web Agent) para Protheus SmartClient Web.
"""

from __future__ import annotations

from typing import Any

from agent.remote.base import RemoteSession

__all__ = [
    "RemoteSession",
    "get_remote_session",
    "BrowserSession",
]

_LAZY: dict[str, tuple[str, str]] = {
    "get_remote_session": ("agent.remote.factory", "get_remote_session"),
    "BrowserSession": ("agent.remote.browser_session", "BrowserSession"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    modulo, atributo = _LAZY[name]
    import importlib

    return getattr(importlib.import_module(modulo), atributo)
