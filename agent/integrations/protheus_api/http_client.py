"""Cliente HTTP Protheus API (schema provisório)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agent.domain.classificacao_nf.modelos import NotaErp
from agent.integrations.protheus_api.mappers import nota_erp_de_dict

logger = logging.getLogger(__name__)


class HttpProtheusApiClient:
    """
    Endpoints provisórios (ajustar quando TEZK42-CONTRATO-API fechar):

      GET  {base}/nfs/tes002/pendentes?nivel_max=
      GET  {base}/nfs/status?filial=&numero=&fornecedor=
         → {"classificada": true|false}
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str = "",
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s
        self._client = client
        self._owns_client = client is None

    def _http(self) -> httpx.Client:
        if self._client is None:
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout_s,
            )
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def listar_nfs_tes002_pendentes(self, *, nivel_max: int | None = None) -> list[NotaErp]:
        params: dict[str, Any] = {}
        if nivel_max is not None:
            params["nivel_max"] = nivel_max
        resp = self._http().get("/nfs/tes002/pendentes", params=params)
        resp.raise_for_status()
        payload = resp.json()
        itens = payload.get("itens") if isinstance(payload, dict) else payload
        if not isinstance(itens, list):
            raise ValueError("resposta Protheus API: esperado lista ou {itens: [...]}")
        notas = [nota_erp_de_dict(item) for item in itens]
        logger.info("[ProtheusApi] listou %s NF(s) TES 002 pendentes", len(notas))
        return notas

    def confirmar_classificada(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
    ) -> bool:
        resp = self._http().get(
            "/nfs/status",
            params={
                "filial": filial_codigo,
                "numero": numero_nf,
                "fornecedor": codigo_fornecedor,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict):
            if "classificada" in payload:
                return bool(payload["classificada"])
            status = str(payload.get("status") or payload.get("STATUS") or "").casefold()
            return status in ("classificada", "classificado")
        return False

    def status_ainda_pendente(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
        codigo_loja: str = "01",
        serie_nf: str = "GOV",
    ) -> bool:
        return not self.confirmar_classificada(
            filial_codigo=filial_codigo,
            numero_nf=numero_nf,
            codigo_fornecedor=codigo_fornecedor,
        )
