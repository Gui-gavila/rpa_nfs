"""Cliente Protheus via genericQuery (Postman FSB / .docs/projeto)."""

from __future__ import annotations

import base64
import calendar
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from agent import config
from agent.domain.classificacao_nf.modelos import NotaErp
from agent.domain.classificacao_nf.objeto_pdf import (
    acb_filial_de_filent,
    montar_ac9_codent,
)
from agent.integrations.protheus_api.mappers import nota_erp_de_dict

logger = logging.getLogger(__name__)

_PATH_GENERIC_QUERY = "/api/framework/v1/genericQuery"
# pageSize 100 × 80 páginas > volumetria mensal (~4000); evita loop se hasNext travar.
_MAX_PAGINAS_SF1 = 80
_CAMPOS_SA2 = "A2_COD,A2_LOJA,A2_CGC,A2_NOME,A2_XNIVLPJ"
_CAMPOS_SM0 = "M0_CODFIL,M0_CGC,M0_NOMECOM"


@dataclass(frozen=True)
class InfoFornecedor:
    """ColetarInfoFornecedor (SA2) — cache por código+loja."""

    cnpj: str = ""
    nome: str = ""
    nivel: int = 0


@dataclass(frozen=True)
class InfoFilial:
    """ColetarInfoFilial (SM0) — cache por código da filial."""

    cnpj: str = ""
    nome: str = ""


def montar_authorization(token: str) -> str | None:
    """
    Monta header Authorization a partir de PROTHEUS_API_TOKEN.

    Formatos aceitos (Postman FSB usa Basic RPA1):
    - ``Basic <base64>`` / ``Bearer <jwt>`` — passa como está
    - ``usuario:senha`` — codifica em Basic
    - token opaco — prefixa Bearer
    """
    raw = (token or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low.startswith("bearer ") or low.startswith("basic "):
        return raw
    if ":" in raw and " " not in raw.split(":", 1)[0]:
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"
    return f"Bearer {raw}"


class GenericQueryProtheusApiClient:
    """
    Lista SF1 (pendentes GOV/portal), resolve AC9_CODENT e ColetarPDF (ACB_OBJETO).
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str = "",
        timeout_s: float = 30.0,
        tenant_id: str = "01",
        verificar_ac9: bool = False,
        ssl_verify: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s
        self.tenant_id = tenant_id or "01"
        self.verificar_ac9 = verificar_ac9
        self.ssl_verify = ssl_verify
        self._client = client
        self._owns_client = client is None

    def _http(self) -> httpx.Client:
        if self._client is None:
            headers: dict[str, str] = {"Accept": "application/json"}
            auth = montar_authorization(self.token)
            if auth:
                headers["Authorization"] = auth
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout_s,
                verify=self.ssl_verify,
            )
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def generic_query(
        self,
        *,
        tables: str,
        fields: str,
        where: str,
        page_size: int = 50,
        page: int = 1,
        filial_filter: bool = False,
    ) -> list[dict[str, Any]]:
        envelope = self._generic_query_envelope(
            tables=tables,
            fields=fields,
            where=where,
            page_size=page_size,
            page=page,
            filial_filter=filial_filter,
        )
        return envelope["items"]

    def _generic_query_envelope(
        self,
        *,
        tables: str,
        fields: str,
        where: str,
        page_size: int = 50,
        page: int = 1,
        filial_filter: bool = False,
    ) -> dict[str, Any]:
        params = {"FilialFilter": "true" if filial_filter else "false"}
        headers = {
            "tables": tables,
            "fields": fields,
            "where": where,
            "pageSize": str(page_size),
            "page": str(max(1, int(page))),
            "TenantId": self.tenant_id,
        }
        resp = self._http().get(_PATH_GENERIC_QUERY, params=params, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, list):
            items = [i for i in payload if isinstance(i, dict)]
            return {"items": items, "hasNext": False}
        if not isinstance(payload, dict):
            raise ValueError("genericQuery: esperado {items: [...]} ou lista")
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("genericQuery: esperado {items: [...]} ou lista")
        items = [i for i in raw_items if isinstance(i, dict)]
        return {
            "items": items,
            "hasNext": payload.get("hasNext"),
            "remainingRecords": payload.get("remainingRecords"),
            "total": payload.get("total"),
        }

    def info_fornecedor(self, *, codigo: str, loja: str) -> InfoFornecedor:
        """ColetarInfoFornecedor — uma query por par código+loja (cache)."""
        chave = f"{codigo}|{loja}"
        cache = getattr(self, "_cache_sa2", None)
        if cache is None:
            self._cache_sa2 = {}
            cache = self._cache_sa2
        if chave in cache:
            return cache[chave]
        info = InfoFornecedor()
        try:
            itens = self.generic_query(
                tables="SA2",
                fields=_CAMPOS_SA2,
                where=(
                    f"A2_COD = '{codigo}' AND A2_LOJA = '{loja}' "
                    "AND SA2.D_E_L_E_T_ = ''"
                ),
                page_size=1,
            )
            if itens:
                raw = itens[0]
                info = InfoFornecedor(
                    cnpj=str(raw.get("a2_cgc") or raw.get("A2_CGC") or ""),
                    nome=str(raw.get("a2_nome") or raw.get("A2_NOME") or "").strip(),
                    nivel=_int_nivel(raw.get("a2_xnivlpj") or raw.get("A2_XNIVLPJ")),
                )
        except Exception as e:
            logger.warning("[ProtheusGQ] SA2 falhou %s: %s", chave, e)
        cache[chave] = info
        return info

    def info_filial(self, *, filial: str) -> InfoFilial:
        """ColetarInfoFilial — uma query por código de filial (cache)."""
        cache = getattr(self, "_cache_sm0", None)
        if cache is None:
            self._cache_sm0 = {}
            cache = self._cache_sm0
        if filial in cache:
            return cache[filial]
        info = InfoFilial()
        try:
            itens = self.generic_query(
                tables="SM0",
                fields=_CAMPOS_SM0,
                where=f"M0_CODFIL = '{filial}'",
                page_size=1,
            )
            if itens:
                raw = itens[0]
                info = InfoFilial(
                    cnpj=str(raw.get("m0_cgc") or raw.get("M0_CGC") or ""),
                    nome=str(
                        raw.get("m0_nomecom") or raw.get("M0_NOMECOM") or ""
                    ).strip(),
                )
        except Exception as e:
            logger.warning("[ProtheusGQ] SM0 falhou %s: %s", filial, e)
        cache[filial] = info
        return info

    def _listar_sf1_paginas(
        self, *, fields: str, where: str, page_size: int
    ) -> list[dict[str, Any]]:
        itens: list[dict[str, Any]] = []
        vistos: set[str] = set()
        for page in range(1, _MAX_PAGINAS_SF1 + 1):
            envelope = self._generic_query_envelope(
                tables="SF1",
                fields=fields,
                where=where,
                page_size=page_size,
                page=page,
            )
            lote = envelope["items"]
            for raw in lote:
                chave = (
                    f"{raw.get('f1_filial') or raw.get('F1_FILIAL') or ''}|"
                    f"{raw.get('f1_doc') or raw.get('F1_DOC') or ''}|"
                    f"{raw.get('f1_fornece') or raw.get('F1_FORNECE') or ''}|"
                    f"{raw.get('f1_loja') or raw.get('F1_LOJA') or ''}"
                )
                if chave in vistos:
                    continue
                vistos.add(chave)
                itens.append(raw)
            if not _tem_proxima_pagina(envelope, lote, page_size):
                logger.info(
                    "[ProtheusGQ] SF1 páginas=%s itens=%s hasNext=%s",
                    page,
                    len(itens),
                    envelope.get("hasNext"),
                )
                return itens
            if not lote:
                break
        logger.warning(
            "[ProtheusGQ] SF1 atingiu teto de páginas (%s); itens=%s",
            _MAX_PAGINAS_SF1,
            len(itens),
        )
        return itens

    def listar_nfs_tes002_pendentes(self, *, nivel_max: int | None = None) -> list[NotaErp]:
        inicio, fim = _periodo_mes_corrente()
        f1_status = config.where_clause_f1_status_pendente()
        where = (
            f"F1_SERIE = 'GOV' AND F1_XPORTAL = 'S' AND {f1_status} "
            f"AND F1_EMISSAO BETWEEN '{inicio}' AND '{fim}' AND SF1.D_E_L_E_T_ = ''"
        )
        fields = (
            "F1_FILIAL,F1_FORNECE,F1_LOJA,F1_DOC,F1_EMISSAO,F1_VALBRUT,"
            "F1_STATUS,F1_SERIE,F1_XPORTAL"
        )
        itens = self._listar_sf1_paginas(fields=fields, where=where, page_size=100)
        notas: list[NotaErp] = []
        for raw in itens:
            nota = nota_erp_de_dict(raw)
            codent = ""
            if nota.numero_nf and nota.serie_nf and nota.codigo_fornecedor and nota.codigo_loja:
                codent = montar_ac9_codent(
                    numero_nf=nota.numero_nf,
                    serie_nf=nota.serie_nf,
                    codigo_fornecedor=nota.codigo_fornecedor,
                    codigo_loja=nota.codigo_loja,
                )
            if self.verificar_ac9 and codent and nota.filial_codigo:
                if not self.existe_vinculo_ac9(
                    filial=nota.filial_codigo, ac9_codent=codent
                ):
                    logger.warning(
                        "[ProtheusGQ] AC9 ausente filial=%s codent=%s — NF ignorada",
                        nota.filial_codigo,
                        codent,
                    )
                    continue
            info_forn = (
                self.info_fornecedor(
                    codigo=nota.codigo_fornecedor, loja=nota.codigo_loja or "01"
                )
                if nota.codigo_fornecedor
                else InfoFornecedor()
            )
            info_fil = (
                self.info_filial(filial=nota.filial_codigo)
                if nota.filial_codigo
                else InfoFilial()
            )
            nivel = nota.nivel if nota.nivel else info_forn.nivel
            nota = NotaErp(
                filial_codigo=nota.filial_codigo,
                filial_nome=nota.filial_nome or info_fil.nome,
                filial_cnpj=nota.filial_cnpj or info_fil.cnpj,
                codigo_fornecedor=nota.codigo_fornecedor,
                codigo_loja=nota.codigo_loja,
                cnpj_fornecedor=nota.cnpj_fornecedor or info_forn.cnpj,
                nome_fornecedor=nota.nome_fornecedor or info_forn.nome,
                numero_nf=nota.numero_nf,
                serie_nf=nota.serie_nf,
                data_emissao=nota.data_emissao,
                data_entrada=nota.data_entrada,
                valor_total=nota.valor_total,
                nivel=nivel,
                cod_objeto=nota.cod_objeto or codent,
                tipo_nf=nota.tipo_nf or "NFS",
                extras=nota.extras,
            )
            if nivel_max is not None and nota.nivel > nivel_max:
                continue
            notas.append(nota)
        logger.info("[ProtheusGQ] listou %s NF(s) SF1 pendentes", len(notas))
        return notas

    def consultar_acb_objeto(self, *, filial: str, ac9_codent: str) -> str:
        """Nome do PDF (ACB_OBJETO) — Postman ColetarPDF: join AC9+ACB."""
        filent = (filial or "").strip()
        codent = (ac9_codent or "").strip()
        acb_filial = acb_filial_de_filent(filent)
        if not filent or not codent or not acb_filial:
            return ""
        where = (
            f"AC9.AC9_FILENT = '{filent}' AND ACB.ACB_FILIAL = '{acb_filial}' "
            f"AND AC9.AC9_CODENT = '{codent}' AND AC9.AC9_CODOBJ = ACB.ACB_CODOBJ"
        )
        try:
            itens = self.generic_query(
                tables="AC9,ACB",
                fields="ACB_OBJETO",
                where=where,
                page_size=10,
            )
        except Exception as e:
            logger.warning(
                "[ProtheusGQ] ColetarPDF falhou filial=%s codent=%s: %s",
                filent,
                codent,
                e,
            )
            return ""
        for raw in itens:
            nome = str(raw.get("acb_objeto") or raw.get("ACB_OBJETO") or "").strip()
            if nome:
                return nome
        return ""

    def existe_vinculo_ac9(self, *, filial: str, ac9_codent: str) -> bool:
        where = (
            f"AC9_FILENT = '{filial}' AND AC9_ENTIDA = 'SF1' "
            f"AND AC9_CODENT = '{ac9_codent}'"
        )
        itens = self.generic_query(
            tables="AC9", fields="AC9_CODENT", where=where, page_size=1
        )
        return bool(itens)

    def _consultar_f1_status(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
        codigo_loja: str = "01",
        serie_nf: str = "GOV",
    ) -> str | None:
        """None se a NF não existir; senão F1_STATUS (pode ser '')."""
        doc = (numero_nf or "").strip().zfill(9)[-9:]
        where = (
            f"F1_FILIAL = '{filial_codigo}' AND F1_DOC = '{doc}' "
            f"AND F1_FORNECE = '{codigo_fornecedor}' AND F1_LOJA = '{codigo_loja}' "
            f"AND F1_SERIE = '{serie_nf}' AND D_E_L_E_T_ = ' '"
        )
        itens = self.generic_query(
            tables="SF1", fields="F1_STATUS", where=where, page_size=1
        )
        if not itens:
            return None
        return str(itens[0].get("f1_status") or itens[0].get("F1_STATUS") or "").strip()

    def status_ainda_pendente(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
        codigo_loja: str = "01",
        serie_nf: str = "GOV",
    ) -> bool:
        """ValidarMudancaStatus pré-coleta: True se existe e F1_STATUS bate o filtro .env."""
        status = self._consultar_f1_status(
            filial_codigo=filial_codigo,
            numero_nf=numero_nf,
            codigo_fornecedor=codigo_fornecedor,
            codigo_loja=codigo_loja,
            serie_nf=serie_nf,
        )
        return status is not None and config.status_bate_filtro_pendente(status)

    def confirmar_classificada(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
        codigo_loja: str = "01",
        serie_nf: str = "GOV",
    ) -> bool:
        status = self._consultar_f1_status(
            filial_codigo=filial_codigo,
            numero_nf=numero_nf,
            codigo_fornecedor=codigo_fornecedor,
            codigo_loja=codigo_loja,
            serie_nf=serie_nf,
        )
        # Postman ValidarMudancaStatus: exemplo "A" apos classificar.
        if status is None:
            return False
        return status != "" and status.upper() not in ("", "N")

    def consultar_f1_status(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
        codigo_loja: str = "01",
        serie_nf: str = "GOV",
    ) -> str | None:
        """Expõe F1_STATUS para log de confirmação pós-UI."""
        return self._consultar_f1_status(
            filial_codigo=filial_codigo,
            numero_nf=numero_nf,
            codigo_fornecedor=codigo_fornecedor,
            codigo_loja=codigo_loja,
            serie_nf=serie_nf,
        )


def _tem_proxima_pagina(
    envelope: dict[str, Any], itens: list[dict[str, Any]], page_size: int
) -> bool:
    """hasNext do P12; se ausente, assume próxima página só com página cheia."""
    if "hasNext" in envelope and envelope["hasNext"] is not None:
        return bool(envelope["hasNext"])
    return len(itens) >= page_size


def _int_nivel(valor: Any) -> int:
    try:
        return int(str(valor or "0").strip() or "0")
    except (TypeError, ValueError):
        return 0


def _periodo_mes_corrente(*, ref: date | None = None) -> tuple[str, str]:
    dia = ref or date.today()
    ultimo = calendar.monthrange(dia.year, dia.month)[1]
    return (
        f"{dia.year:04d}{dia.month:02d}01",
        f"{dia.year:04d}{dia.month:02d}{ultimo:02d}",
    )
