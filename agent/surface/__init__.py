"""Camada Surface — exporta a ABC e resolve backends sob demanda.

Neste fork: PlaywrightSurface (Protheus SmartClient Web).
"""

from __future__ import annotations

from typing import Any

from agent.surface.base import Surface

__all__ = ["Surface", "PlaywrightSurface"]

_LAZY: dict[str, tuple[str, str]] = {
    "PlaywrightSurface": ("agent.surface.browser", "PlaywrightSurface"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    modulo, atributo = _LAZY[name]
    import importlib

    return getattr(importlib.import_module(modulo), atributo)
