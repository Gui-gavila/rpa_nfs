"""Framework Carol App RPA — especialização Tezk42 (código interno FSB).

Superfície de import deliberadamente mínima. As camadas (`vpn`, `remote`,
`surface`, `erp`) resolvem seus backends sob demanda.
"""

from __future__ import annotations

from typing import Any

from agent.config import AGENT_ENV, ERP_TYPE, IS_PRODUCTION, RUNTIME_MODE

__all__ = [
    "AGENT_ENV",
    "IS_PRODUCTION",
    "RUNTIME_MODE",
    "ERP_TYPE",
    "get_vpn",
    "get_erp_agent",
]

_LAZY: dict[str, tuple[str, str]] = {
    "get_vpn": ("agent.vpn.factory", "get_vpn"),
    "get_erp_agent": ("agent.erp.factory", "get_erp_agent"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    modulo, atributo = _LAZY[name]
    import importlib

    return getattr(importlib.import_module(modulo), atributo)
