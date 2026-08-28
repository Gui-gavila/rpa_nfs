"""Mapeamento JSON provisório → NotaErp (até contrato FSB fechar)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

from agent.domain.classificacao_nf.modelos import NotaErp


def _get(dados: Mapping[str, Any], *chaves: str, default: Any = "") -> Any:
    for chave in chaves:
        if chave in dados and dados[chave] is not None:
            return dados[chave]
        upper = chave.upper()
        if upper in dados and dados[upper] is not None:
            return dados[upper]
        lower = chave.lower()
        if lower in dados and dados[lower] is not None:
            return dados[lower]
    # genericQuery Protheus devolve campos em minúsculas (f1_filial, …)
    lower_map = {str(k).lower(): v for k, v in dados.items()}
    for chave in chaves:
        low = chave.lower()
        if low in lower_map and lower_map[low] is not None:
            return lower_map[low]
    return default


def _data(valor: Any) -> date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    texto = str(valor).strip()
    if "/" in texto:
        dia, mes, ano = texto.split("/", 2)
        return date(int(ano), int(mes), int(dia))
    return date.fromisoformat(texto[:10])


def _decimal(valor: Any) -> Decimal:
    if valor is None or valor == "":
        return Decimal("0")
    return Decimal(str(valor).replace(",", "."))


def nota_erp_de_dict(dados: Mapping[str, Any]) -> NotaErp:
    """Aceita chaves pt-BR do CR ou aliases snake/UPPER comuns em REST."""
    return NotaErp(
        filial_codigo=str(_get(dados, "filial_codigo", "FILIAL", "filial", "F1_FILIAL")),
        filial_nome=str(_get(dados, "filial_nome", "NOME_FILIAL")),
        filial_cnpj=str(_get(dados, "filial_cnpj", "CNPJ_FILIAL", "cnpj_tomador")),
        codigo_fornecedor=str(
            _get(dados, "codigo_fornecedor", "COD_FORNECEDOR", "fornecedor", "F1_FORNECE")
        ),
        codigo_loja=str(_get(dados, "codigo_loja", "COD_LOJA", "loja", "F1_LOJA")),
        cnpj_fornecedor=str(
            _get(dados, "cnpj_fornecedor", "CNPJ_FORNECEDOR", "cnpj_prestador")
        ),
        nome_fornecedor=str(
            _get(dados, "nome_fornecedor", "NOME_FORNECEDOR", "A2_NOME")
        ),
        numero_nf=str(_get(dados, "numero_nf", "NUMERO_NF", "numero", "F1_DOC")),
        serie_nf=str(_get(dados, "serie_nf", "SERIE_NF", "serie", "F1_SERIE")),
        data_emissao=_data(_get(dados, "data_emissao", "DATA_EMISSAO", "F1_EMISSAO", default=None)),
        data_entrada=_data(_get(dados, "data_entrada", "DATA_ENTRADA", default=None)),
        valor_total=_decimal(
            _get(dados, "valor_total", "VALOR_TOTAL", "F1_VALBRUT", default="0")
        ),
        nivel=int(_get(dados, "nivel", "NIVEL", "NIVEL_PJ", "A2_XNIVLPJ", default=0) or 0),
        cod_objeto=str(
            _get(
                dados,
                "cod_objeto",
                "COD_OBJETO",
                "codigo_objeto",
                "AC9_CODENT",
                "ac9_codent",
            )
        ),
        tipo_nf=str(_get(dados, "tipo_nf", "TIPO_NF", "tipo") or "NFS"),
        extras=dict(dados),
    )
