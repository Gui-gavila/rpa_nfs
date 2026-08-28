# -*- coding: utf-8 -*-
"""ControleClassificacao.xlsx como planilha viva (fonte da verdade operacional)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Mapping

from agent.reporting.enriquecer_controle import COLUNAS_AVALIACAO, gravar_avaliacao_xlsx

logger = logging.getLogger(__name__)

FLAG_SIM = "Sim"
FLAG_NAO = "Não"

CAMPOS_AVANCO: frozenset[str] = frozenset(
    {
        "PDF_RECUPERADO",
        "LYNN_PROCESSADO",
        "STATUS_LYNN",
        "STATUS_CLASSIFICACAO_PROTHEUS",
        "STATUS",
        "MOTIVO",
        "COD_ENTIDADE",
        "NATUREZA_DESPESA",
        "NATUREZA_RENDIMENTO",
        "COD_TRIBUTACAO",
        "COD_RETENCAO_IRRF",
        "COD_RETENCAO_PCC",
        "LAYOUT",
        "MEI",
        "ISSQN",
        "IRRF",
        "PIS",
        "COFINS",
        "CSLL",
        "NUMERO_NF_PDF",
        "TIPO_NF_PDF",
        "DATA_EMISSAO_NF_PDF",
        "VALOR_TOTAL_NF_PDF",
        "CNPJ_TOMADOR_PDF",
        "CNPJ_PRESTADOR_PDF",
        "RETENCAO",
        "ISSQN_RETIDO",
        "TIMESTAMP ENTRADA",
        "TIMESTAMP SAIDA",
    }
)


def _s(v: Any) -> str:
    if v is None:
        return ""
    text = str(v).strip()
    if text in {"-", "None", "null"}:
        return ""
    return text


def eh_sim(valor: Any) -> bool:
    s = _s(valor).casefold()
    return s in {"sim", "s", "1", "true", "yes"}


def chave_linha(linha: Mapping[str, Any]) -> str:
    filial = _s(linha.get("COD_FILIAL") or linha.get("FILIAL"))
    numero = _s(linha.get("NUMERO_NF"))
    forn = _s(linha.get("COD_FORNECEDOR"))
    return f"{filial}|{numero}|{forn}"


def linha_vazia() -> dict[str, str]:
    return {c: "" for c in COLUNAS_AVALIACAO}


def normalizar_linha(bruta: Mapping[str, Any]) -> dict[str, str]:
    """Garante schema atual; migra STATUS_PROCESSAMENTO legado → STATUS_LYNN."""
    out = linha_vazia()
    for c in COLUNAS_AVALIACAO:
        if c in bruta:
            out[c] = _s(bruta.get(c))
    if not out["COD_FILIAL"]:
        out["COD_FILIAL"] = _s(bruta.get("FILIAL"))
    if not out["SERIE_NF"]:
        out["SERIE_NF"] = _s(bruta.get("SERIE_PDF"))
    if not out["STATUS_LYNN"]:
        out["STATUS_LYNN"] = _s(bruta.get("STATUS_PROCESSAMENTO"))
    return out


def carregar_indice(caminho: str | Path) -> dict[str, dict[str, str]]:
    from agent.reporting.enriquecer_controle import ler_linhas_ops_xlsx

    path = Path(caminho)
    if not path.is_file():
        return {}
    indice: dict[str, dict[str, str]] = {}
    for bruta in ler_linhas_ops_xlsx(path):
        linha = normalizar_linha(bruta)
        chave = chave_linha(linha)
        if chave == "||":
            continue
        indice[chave] = linha
    return indice


def salvar_indice(caminho: str | Path, indice: Mapping[str, Mapping[str, str]]) -> Path:
    linhas = [normalizar_linha(v) for _, v in sorted(indice.items())]
    path = gravar_avaliacao_xlsx(caminho, linhas)
    logger.info("[controle_vivo] gravou %s linha(s) → %s", len(linhas), path)
    return path


def merge_linha(
    existente: Mapping[str, Any] | None,
    novo: Mapping[str, Any],
    *,
    forcar: Iterable[str] | None = None,
) -> dict[str, str]:
    """Merge: preenche só células vazias; ``forcar`` sobrescreve sempre."""
    base = normalizar_linha(existente or {})
    entrante = normalizar_linha(novo)
    forcar_set = set(forcar or ())
    for col in COLUNAS_AVALIACAO:
        val_novo = entrante.get(col, "")
        if not val_novo:
            continue
        if col in forcar_set or not base.get(col):
            base[col] = val_novo
    return base


def upsert_indice(
    indice: dict[str, dict[str, str]],
    linha: Mapping[str, Any],
    *,
    forcar: Iterable[str] | None = None,
) -> str:
    chave = chave_linha(linha)
    if chave == "||":
        raise ValueError("linha_controle_sem_chave")
    indice[chave] = merge_linha(indice.get(chave), linha, forcar=forcar)
    return chave


def item_de_linha_controle(linha: Mapping[str, Any]) -> Any:
    """Espelho técnico ItemCheckpoint a partir de uma linha da planilha viva."""
    from agent.jobs.classificar_nf.checkpoint import ItemCheckpoint, chave_nf

    filial = _s(linha.get("COD_FILIAL"))
    numero = _s(linha.get("NUMERO_NF"))
    forn = _s(linha.get("COD_FORNECEDOR"))
    nivel_raw = _s(linha.get("NIVEL_PJ")) or "0"
    try:
        nivel = int(nivel_raw)
    except ValueError:
        nivel = 0
    return ItemCheckpoint(
        chave=chave_nf(
            filial_codigo=filial, numero_nf=numero, codigo_fornecedor=forn
        ),
        filial_codigo=filial,
        numero_nf=numero,
        codigo_fornecedor=forn,
        codigo_loja=_s(linha.get("COD_LOJA")),
        nome_fornecedor=_s(linha.get("NOME_FORNECEDOR")),
        filial_nome=_s(linha.get("NOME_FILIAL")),
        cod_objeto=_s(linha.get("COD_ENTIDADE")),
        ac9_codent=_s(linha.get("COD_ENTIDADE")),
        nivel=nivel,
        serie_nf=_s(linha.get("SERIE_NF")),
        data_emissao_nf=_s(linha.get("DATA_EMISSAO_NF")),
        valor_total_nf=_s(linha.get("VALOR_TOTAL_NF")),
        status=_s(linha.get("STATUS")),
        motivo=_s(linha.get("MOTIVO")) or None,
        codigo_servico=_s(linha.get("COD_TRIBUTACAO")) or None,
        natureza_despesa=_s(linha.get("NATUREZA_DESPESA")) or None,
        natureza_rendimento=_s(linha.get("NATUREZA_RENDIMENTO")) or None,
        data_vencimento=None,
        issqn=_s(linha.get("ISSQN")) or "0",
        irrf=_s(linha.get("IRRF")) or "0",
        pis=_s(linha.get("PIS")) or "0",
        cofins=_s(linha.get("COFINS")) or "0",
        csll=_s(linha.get("CSLL")) or "0",
    )
