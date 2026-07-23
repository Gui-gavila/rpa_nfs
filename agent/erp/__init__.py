"""Camada ErpAgent — exporta a ABC e resolve especializações sob demanda.

A fábrica (`agent.erp.factory.get_erp_agent`) é o ponto de seleção por
ERP_TYPE. Os agentes concretos são importados preguiçosamente para que instalar
só as dependências de um ERP continue sendo suficiente.
"""

from __future__ import annotations

from typing import Any

from agent.erp.base import ErpAgent

__all__ = ["ErpAgent", "get_erp_agent", "ProtheusAgent"]

_LAZY: dict[str, tuple[str, str]] = {
    "get_erp_agent": ("agent.erp.factory", "get_erp_agent"),
    "ProtheusAgent": ("agent.erp.protheus.agent", "ProtheusAgent"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    modulo, atributo = _LAZY[name]
    import importlib

    return getattr(importlib.import_module(modulo), atributo)
