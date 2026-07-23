"""Fábrica de agentes ERP — seleciona a especialização por ERP_TYPE.

Registrar um ERP novo = implementar `ErpAgent` e acrescentar um construtor
aqui. Cada construtor recebe a Surface já pronta e lê o próprio perfil do
config, de modo que o worker não precisa saber nada de ERP específico.
"""

from __future__ import annotations

import logging
from typing import Any

from agent import config
from agent.erp.base import ErpAgent

logger = logging.getLogger(__name__)


def _agente_protheus(surface: Any, **kwargs: Any) -> ErpAgent:
    from agent.erp.protheus.agent import ProtheusAgent

    perfil = config.resolve_protheus_perfil()
    return ProtheusAgent(
        surface,
        username=perfil["username"],
        password=perfil["password"],
        programa=perfil["programa"],
        ambiente=perfil["ambiente"],
        screenshots_dir=config.SCREENSHOTS_DIR,
        nav_timeout_s=config.PROTHEUS_UI_LOAD_TIMEOUT_S,
        **kwargs,
    )


_CONSTRUTORES = {
    "protheus": _agente_protheus,
}


def get_erp_agent(surface: Any, *, erp: str | None = None, **kwargs: Any) -> ErpAgent:
    """Instancia o ErpAgent do ERP ativo, com a Surface injetada."""
    tipo = config.normalize_erp_type(erp)
    logger.info("[ERP Factory] ERP_TYPE=%s", tipo)
    try:
        return _CONSTRUTORES[tipo](surface, **kwargs)
    except KeyError as e:
        raise ValueError(f"ERP_TYPE não suportado: {tipo!r}") from e
