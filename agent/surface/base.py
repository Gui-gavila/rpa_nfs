"""Superfície de automação — contrato mínimo de interação visual.

Neste fork: PlaywrightSurface sobre o canvas do Protheus SmartClient Web.

O contrato é deliberadamente pequeno. Capacidades específicas de browser
(ex.: manipular DOM) NÃO entram na ABC — ficam na classe concreta.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Surface(ABC):
    """Contrato mínimo para interagir com uma superfície visual."""

    @abstractmethod
    def capture(self) -> Any:
        """Captura o frame atual (np.ndarray BGR) ou None se indisponível."""

    @abstractmethod
    def click(self, x: int, y: int) -> None:
        """Clique em coordenada da superfície."""

    @abstractmethod
    def type_text(self, text: str, *, delay_ms: int = 0) -> None:
        """Digita texto no elemento com foco."""

    @abstractmethod
    def press(self, key: str) -> None:
        """Pressiona tecla ou atalho (ex.: 'enter', 'tab', 'alt+i')."""
