"""Normalização e validação de cabeçalho PDF × ERP (RN-04)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from agent.domain.classificacao_nf.modelos import NotaErp, NotaPdf
from agent.domain.classificacao_nf.status import MOTIVOS


def so_digitos(valor: str | None) -> str:
    return "".join(ch for ch in (valor or "") if ch.isdigit())


def normalizar_numero_nf(valor: str | None) -> str:
    texto = (valor or "").strip()
    if not texto:
        return ""
    if texto.isdigit():
        return str(int(texto))
    return texto.lstrip("0") or "0"


def normalizar_cnpj(valor: str | None) -> str:
    return so_digitos(valor)


def normalizar_tipo(valor: str | None) -> str:
    return (valor or "").strip().casefold()


def normalizar_valor(valor: Decimal | int | float | str | None) -> Decimal:
    if valor is None or valor == "":
        return Decimal("0.00")
    quantia = Decimal(str(valor))
    return quantia.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ResultadoValidacao:
    ok: bool
    motivo: str | None = None


def _campo_essencial_ausente(pdf: NotaPdf) -> str | None:
    if pdf.campo_ausente:
        return pdf.campo_ausente
    obrigatorios: list[tuple[str, Any]] = [
        ("Número da Nota Fiscal", pdf.numero_nf),
        ("CNPJ Prestador/Emitente", pdf.cnpj_prestador),
        ("CNPJ Tomador", pdf.cnpj_tomador),
        ("Código de Serviço", pdf.codigo_servico),
        ("Valor Total", pdf.valor_total),
        ("Tipo da Nota Fiscal", pdf.tipo_nf),
    ]
    for nome, valor in obrigatorios:
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            return nome
    if pdf.data_emissao is None:
        return "Data de Emissão"
    return None


def validar_cabecalho(erp: NotaErp, pdf: NotaPdf) -> ResultadoValidacao:
    """Compara cabeçalho ERP × PDF. Primeira divergência encerra (ordem do CR)."""
    ausente = _campo_essencial_ausente(pdf)
    if ausente:
        return ResultadoValidacao(False, MOTIVOS.campo_nao_coletado(ausente))

    if normalizar_numero_nf(erp.numero_nf) != normalizar_numero_nf(pdf.numero_nf):
        return ResultadoValidacao(False, MOTIVOS.NUMERO_DIVERGENTE)

    if normalizar_cnpj(erp.cnpj_fornecedor) != normalizar_cnpj(pdf.cnpj_prestador):
        return ResultadoValidacao(False, MOTIVOS.PRESTADOR_DIVERGENTE)

    if normalizar_cnpj(erp.filial_cnpj) != normalizar_cnpj(pdf.cnpj_tomador):
        return ResultadoValidacao(False, MOTIVOS.TOMADOR_DIVERGENTE)

    if erp.data_emissao != pdf.data_emissao:
        return ResultadoValidacao(False, MOTIVOS.DATA_EMISSAO_DIVERGENTE)

    if normalizar_valor(erp.valor_total) != normalizar_valor(pdf.valor_total):
        return ResultadoValidacao(False, MOTIVOS.VALOR_DIVERGENTE)

    if normalizar_tipo(erp.tipo_nf) != normalizar_tipo(pdf.tipo_nf):
        return ResultadoValidacao(False, MOTIVOS.TIPO_DIVERGENTE)

    return ResultadoValidacao(True, None)
