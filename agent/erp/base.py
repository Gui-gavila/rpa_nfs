"""Agente ERP — contrato de negócio sobre uma Surface.

A Surface entra pelo construtor (injeção), e é essa costura que torna o agente
independente de como a tela é alcançada: o mesmo agente roda sobre desktop
remoto ou sobre canvas de browser trocando apenas o objeto injetado.

Especializar o framework para um ERP novo = implementar esta ABC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.surface.base import Surface


class ErpAgent(ABC):
    """Agente de negócio sobre uma Surface (desktop ou browser)."""

    def __init__(self, surface: Surface) -> None:
        self.surface = surface

    @abstractmethod
    def login(self) -> bool:
        """Autentica no ERP. True se a sessão está pronta para operar."""

    @abstractmethod
    def run(self, **kwargs: Any) -> dict[str, Any]:
        """Executa a rotina de negócio.

        Devolve o contrato de resultado de `agent.pipeline.novo_resultado`.
        Erros esperados viram `{"ok": False, "erro": "<slug>"}` em vez de
        exceção — o worker precisa reportar o passo que falhou, não um stack.
        """
