"""Sessão remota — como a UI do ERP passa a existir e ficar acessível.

Neste fork Tezk42/FSB:

    BrowserSession  Chromium + navegação até a URL do SmartClient (Protheus)

Tratar o browser como uma RemoteSession mantém o pipeline
(preflight → vpn → sessão → login → run) estável.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class RemoteSession(ABC):
    """Contrato para estabelecer e encerrar uma sessão de UI."""

    @abstractmethod
    def connect(self) -> bool:
        """Abre/anexa a sessão. True se pronta para automação."""

    @abstractmethod
    def disconnect(self) -> None:
        """Encerra ou desanexa a sessão."""

    @abstractmethod
    def is_ready(self) -> bool:
        """True se a sessão ainda está utilizável."""
