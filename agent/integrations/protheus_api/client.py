"""Contrato e fábrica do cliente Protheus API."""

from __future__ import annotations

from typing import Protocol

from agent.domain.classificacao_nf.modelos import NotaErp


class ProtheusApiClient(Protocol):
    """Consulta ERP sem UI (após VPN na VM)."""

    def listar_nfs_tes002_pendentes(self, *, nivel_max: int | None = None) -> list[NotaErp]:
        """NFs TES 002 não classificadas. `nivel_max` filtra fase (ex.: 3 = Fase 1)."""

    def confirmar_classificada(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
    ) -> bool:
        """True se o ERP reporta status Classificada."""


def criar_protheus_api_client(
    *,
    modo: str | None = None,
    base_url: str | None = None,
    token: str | None = None,
    timeout_s: float | None = None,
    fake: ProtheusApiClient | None = None,
) -> ProtheusApiClient:
    """Resolve client por config. `modo=fake` ou URL vazia → Fake (ou `fake` injetado)."""
    from agent import config

    modo_efetivo = (modo if modo is not None else config.PROTHEUS_API_MODE).strip().lower()
    url = (base_url if base_url is not None else config.PROTHEUS_API_BASE_URL).strip()
    tok = token if token is not None else config.PROTHEUS_API_TOKEN
    timeout = float(
        timeout_s if timeout_s is not None else config.PROTHEUS_API_TIMEOUT_S
    )

    if modo_efetivo == "fake" or not url:
        if fake is not None:
            return fake
        from agent.integrations.protheus_api.fake import FakeProtheusApiClient

        return FakeProtheusApiClient()

    estilo = (config.PROTHEUS_API_STYLE or "generic_query").strip().lower()
    if estilo in ("provisional", "rest_provisorio", "legado"):
        from agent.integrations.protheus_api.http_client import HttpProtheusApiClient

        return HttpProtheusApiClient(base_url=url, token=tok, timeout_s=timeout)

    from agent.integrations.protheus_api.generic_query import GenericQueryProtheusApiClient

    return GenericQueryProtheusApiClient(
        base_url=url,
        token=tok,
        timeout_s=timeout,
        tenant_id=config.PROTHEUS_API_TENANT_ID,
        verificar_ac9=config.PROTHEUS_AC9_VERIFY,
        ssl_verify=config.PROTHEUS_API_SSL_VERIFY,
    )
