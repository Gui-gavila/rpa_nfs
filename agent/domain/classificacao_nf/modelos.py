"""Modelos de dados do domínio de classificação NF."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ImpostosNf:
    """Impostos extraídos do PDF (valores monetários)."""

    issqn: Decimal = Decimal("0")
    irrf: Decimal = Decimal("0")
    pis: Decimal = Decimal("0")
    cofins: Decimal = Decimal("0")
    csll: Decimal = Decimal("0")

    @property
    def tem_iss_a_recolher(self) -> bool:
        return self.issqn > 0

    @property
    def tem_irrf(self) -> bool:
        return self.irrf > 0

    @property
    def tem_pcc(self) -> bool:
        return self.pis > 0 or self.cofins > 0 or self.csll > 0

    @property
    def tem_retencao(self) -> bool:
        return self.tem_irrf or self.tem_pcc


@dataclass(frozen=True)
class NotaErp:
    """Campos da NF conforme retorno da consulta ao ERP (lista de pendentes)."""

    filial_codigo: str
    filial_nome: str = ""
    filial_cnpj: str = ""
    codigo_fornecedor: str = ""
    codigo_loja: str = ""
    cnpj_fornecedor: str = ""
    nome_fornecedor: str = ""
    numero_nf: str = ""
    serie_nf: str = ""
    data_emissao: date | None = None
    data_entrada: date | None = None
    valor_total: Decimal = Decimal("0")
    nivel: int = 0
    cod_objeto: str = ""
    tipo_nf: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClassificacaoLynn:
    """Bloco ``classificacao`` do agente LYNN (prompt V7+)."""

    status: str | None = None
    motivo: str | None = None
    tipo_nf_pdf: bool | None = None
    layout: str | None = None
    cod_tributacao: str | None = None
    mei: bool = False
    issqn_retido: bool = False
    natureza_rendimento: str | None = None
    natureza_despesa: str | None = None
    cod_retencao_irrf: str | None = None
    cod_retencao_pcc: str | None = None

    @property
    def validacao_ok(self) -> bool:
        if not self.status:
            return False
        compacto = self.status.replace(" ", "").casefold()
        return compacto in {"validacaook", "ok", "validado"}

    @property
    def nao_classificado(self) -> bool:
        if not self.status:
            return False
        s = self.status.casefold()
        return "não classificado" in s or "nao classificado" in s


@dataclass(frozen=True)
class NotaPdf:
    """Campos extraídos do PDF (LYNN ou equivalente)."""

    numero_nf: str = ""
    cnpj_prestador: str = ""
    cnpj_tomador: str = ""
    codigo_servico: str = ""
    impostos: ImpostosNf = field(default_factory=ImpostosNf)
    valor_total: Decimal = Decimal("0")
    tipo_nf: str = ""
    data_emissao: date | None = None
    campo_ausente: str | None = None
    classificacao: ClassificacaoLynn | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreparacaoClassificacao:
    """Resultado do data-plane de domínio (antes da UI MATA103)."""

    ok: bool
    status: str
    motivo: str | None = None
    codigo_servico: str | None = None
    natureza_despesa: str | None = None
    natureza_rendimento: str | None = None
    codigo_retencao: str | None = None
    data_vencimento: date | None = None
    nota_erp: NotaErp | None = None
    nota_pdf: NotaPdf | None = None
