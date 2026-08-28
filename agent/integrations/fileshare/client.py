"""Contrato e fábrica do fileshare de PDFs."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class FileshareClient(Protocol):
    def obter_pdf(
        self,
        cod_objeto: str,
        destino: str | Path,
        *,
        candidatos: list[str] | None = None,
    ) -> Path:
        """Copia/localiza o PDF do objeto e grava (ou aponta) em `destino`."""


def criar_fileshare_client(
    *,
    modo: str | None = None,
    root: str | None = None,
    fake: FileshareClient | None = None,
) -> FileshareClient:
    from agent import config

    modo_efetivo = (modo if modo is not None else config.PDF_SHARE_MODE).strip().lower()
    raiz = (root if root is not None else config.PDF_SHARE_ROOT).strip()

    if modo_efetivo == "fake" or not raiz:
        if fake is not None:
            return fake
        from agent.integrations.fileshare.fake import FakeFileshareClient

        return FakeFileshareClient()

    from agent.integrations.fileshare.local import LocalFileshareClient

    return LocalFileshareClient(root=raiz)
