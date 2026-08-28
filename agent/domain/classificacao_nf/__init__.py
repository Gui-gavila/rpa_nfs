"""Domínio da classificação de NFS TES 002 (regras puras, sem UI/HTTP)."""

from __future__ import annotations

from agent.domain.classificacao_nf.deparas import (
    TabelasDepara,
    carregar_tabela_csv,
    resolver_codigo_servico,
    resolver_natureza_despesa,
    resolver_natureza_rendimento,
)
from agent.domain.classificacao_nf.layout import (
    LAYOUTS_PERMITIDOS,
    layout_permitido,
    motivo_recusa_layout_ou_tipo,
)
from agent.domain.classificacao_nf.modelos import (
    ClassificacaoLynn,
    ImpostosNf,
    NotaErp,
    NotaPdf,
    PreparacaoClassificacao,
)
from agent.domain.classificacao_nf.objeto_pdf import (
    acb_filial_de_filent,
    candidatos_nomes_pdf,
    montar_ac9_codent,
    montar_ac9_codent_de_nota,
    nome_arquivo_pdf_fsb,
    nome_arquivo_pdf_fsb_de_nota,
)
from agent.domain.classificacao_nf.preparar import preparar_classificacao
from agent.domain.classificacao_nf.status import MOTIVOS, StatusNf
from agent.domain.classificacao_nf.validacao import validar_cabecalho
from agent.domain.classificacao_nf.vencimento import calcular_vencimento
from agent.domain.classificacao_nf.xlsx_loader import (
    carregar_tabela_arquivo,
    carregar_tabela_xlsx,
    carregar_tabelas_depara,
    carregar_tabelas_depara_de_config,
)

__all__ = [
    "ClassificacaoLynn",
    "ImpostosNf",
    "LAYOUTS_PERMITIDOS",
    "MOTIVOS",
    "NotaErp",
    "NotaPdf",
    "PreparacaoClassificacao",
    "StatusNf",
    "TabelasDepara",
    "acb_filial_de_filent",
    "calcular_vencimento",
    "candidatos_nomes_pdf",
    "carregar_tabela_arquivo",
    "carregar_tabela_csv",
    "carregar_tabela_xlsx",
    "carregar_tabelas_depara",
    "carregar_tabelas_depara_de_config",
    "layout_permitido",
    "motivo_recusa_layout_ou_tipo",
    "montar_ac9_codent",
    "montar_ac9_codent_de_nota",
    "nome_arquivo_pdf_fsb",
    "nome_arquivo_pdf_fsb_de_nota",
    "preparar_classificacao",
    "resolver_codigo_servico",
    "resolver_natureza_despesa",
    "resolver_natureza_rendimento",
    "validar_cabecalho",
]
