"""Colunas canónicas do relatório de execução (CR FSB — classificação TES 002)."""

from __future__ import annotations

# Ordem estável para CSV/XLSX. Campos sem fonte no checkpoint ficam vazios.
COLUNAS_RELATORIO_NF: tuple[str, ...] = (
    "FILIAL",
    "COD_FORNECEDOR",
    "NOME_FORNECEDOR",
    "NUMERO_NF",
    "TIPO_NF",
    "DATA_EMISSAO_NF",
    "DATA_ENTRADA_NF",
    "VALOR_TOTAL_NF",
    "NIVEL_PJ",
    "TP_ENTRADA",
    "SERIE_PDF",
    "COD_OBJETO",
    "NUMERO_NF_PDF",
    "TIPO_NF_PDF",
    "DATA_EMISSAO_NF_PDF",
    "VALOR_TOTAL_NF_PDF",
    "COD_SERVICO",
    "ISSQN",
    "IRRF",
    "PIS",
    "COFINS",
    "CSLL",
    "NATUREZA_DESPESA",
    "NATUREZA_RENDIMENTO",
    "COD_RETENCAO_IRRF",
    "COD_RETENCAO_PCC",
    "STATUS",
    "MOTIVO",
)
