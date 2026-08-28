"""Contrato e fábrica do cliente LYNN."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent.domain.classificacao_nf.modelos import NotaPdf


class LynnClient(Protocol):
    def extrair_nf(self, pdf_path: str | Path) -> NotaPdf:
        """Extrai campos obrigatórios do PDF da NFS."""


def criar_lynn_client(
    *,
    modo: str | None = None,
    base_url: str | None = None,
    token: str | None = None,
    timeout_s: float | None = None,
    fake: LynnClient | None = None,
) -> LynnClient:
    from agent import config

    modo_efetivo = (modo if modo is not None else config.LYNN_API_MODE).strip().lower()
    # Preferir LYNN_BASE_URL (host DTA); fallback LYNN_API_BASE_URL legado.
    url = (
        base_url
        if base_url is not None
        else (config.LYNN_BASE_URL or config.LYNN_API_BASE_URL)
    ).strip()
    tok = token if token is not None else (
        config.LYNN_API_TOKEN or config.LYNN_API_KEY
    )
    timeout = float(timeout_s if timeout_s is not None else config.LYNN_API_TIMEOUT_S)

    if modo_efetivo == "fake" or not url:
        if fake is not None:
            return fake
        from agent.integrations.lynn.fake import FakeLynnClient

        return FakeLynnClient()

    from agent.integrations.lynn.http_client import HttpLynnClient

    return HttpLynnClient(
        base_url=url,
        token=tok,
        project=config.LYNN_PROJECT,
        agent_id=config.LYNN_AGENT_ID,
        workflow_id=config.LYNN_WORKFLOW_ID,
        run_mode=config.LYNN_RUN_MODE,
        auth_mode=config.LYNN_AUTH_MODE,
        timeout_s=timeout,
        message=config.LYNN_MESSAGE,
    )
