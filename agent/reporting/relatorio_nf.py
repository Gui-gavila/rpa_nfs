"""Gera relatório gerencial CSV/XLSX a partir do checkpoint."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from agent.erp.protheus.mata103 import COD_RETENCAO_IR, COD_RETENCAO_PCC
from agent.jobs.classificar_nf.checkpoint import Checkpoint, ItemCheckpoint
from agent.reporting.colunas import COLUNAS_RELATORIO_NF
from agent.reporting.enriquecer_controle import (
    COLUNAS_AVALIACAO,
    gravar_avaliacao_xlsx,
    mapear_linha_avaliacao,
)

logger = logging.getLogger(__name__)


def item_para_linha(item: ItemCheckpoint) -> dict[str, str]:
    """Mapeia ItemCheckpoint → colunas do CR ops (lacunas = string vazia)."""
    ret_ir = COD_RETENCAO_IR if item.tem_irrf else ""
    ret_pcc = COD_RETENCAO_PCC if item.tem_pcc else ""
    return {
        "FILIAL": item.filial_codigo or "",
        "COD_FORNECEDOR": item.codigo_fornecedor or "",
        "NOME_FORNECEDOR": item.nome_fornecedor or "",
        "NUMERO_NF": item.numero_nf or "",
        "TIPO_NF": item.tipo_nf or "",
        "DATA_EMISSAO_NF": item.data_emissao_nf or "",
        "DATA_ENTRADA_NF": item.data_entrada_nf or "",
        "VALOR_TOTAL_NF": item.valor_total_nf or "",
        "NIVEL_PJ": str(item.nivel or ""),
        "TP_ENTRADA": "",
        "SERIE_PDF": item.serie_nf or "",
        "COD_OBJETO": item.cod_objeto or "",
        "NUMERO_NF_PDF": item.numero_nf or "",
        "TIPO_NF_PDF": "",
        "DATA_EMISSAO_NF_PDF": "",
        "VALOR_TOTAL_NF_PDF": "",
        "COD_SERVICO": item.codigo_servico or "",
        "ISSQN": item.issqn or "0",
        "IRRF": item.irrf or "0",
        "PIS": item.pis or "0",
        "COFINS": item.cofins or "0",
        "CSLL": item.csll or "0",
        "NATUREZA_DESPESA": item.natureza_despesa or "",
        "NATUREZA_RENDIMENTO": item.natureza_rendimento or "",
        "COD_RETENCAO_IRRF": ret_ir,
        "COD_RETENCAO_PCC": ret_pcc,
        "STATUS": item.status or "",
        "MOTIVO": item.motivo or "",
    }




def item_para_linha_avaliacao(item: ItemCheckpoint) -> dict[str, str]:
    """Linha ControleClassificacao no schema Avaliação (ops + JSON Lynn local).

    Não preenche TIMESTAMP ENTRADA/SAIDA (negócio: entrada=PDF recuperado;
    saída=classificada no Protheus — ver coleta_erp / ProtheusAgent).
    """
    ops = item_para_linha(item)
    ops["NOME_FILIAL"] = item.filial_nome or ""
    ops["COD_LOJA"] = item.codigo_loja or ""
    ops["COD_ENTIDADE"] = item.ac9_codent or item.cod_objeto or ""
    ops["VENCIMENTO"] = item.data_vencimento or ""
    extracao = classificacao = None
    if item.pdf_path:
        pdf = Path(item.pdf_path)
        jpath = pdf.with_suffix(".json")
        if jpath.is_file():
            try:
                from agent.integrations.lynn.offline import carregar_lynn_arquivo

                payload = carregar_lynn_arquivo(jpath)
                extracao = payload.extracao
                classificacao = payload.classificacao
            except Exception as e:
                logger.warning("[reporting] JSON LYNN ilegível %s: %s", jpath, e)
    return mapear_linha_avaliacao(
        ops=ops,
        extracao=extracao,
        classificacao=classificacao,
    )


def _escrever_csv(caminho: Path, linhas: list[dict[str, str]]) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=list(COLUNAS_RELATORIO_NF), extrasaction="ignore"
        )
        writer.writeheader()
        for linha in linhas:
            writer.writerow({c: linha.get(c, "") for c in COLUNAS_RELATORIO_NF})
    return caminho


def _escrever_xlsx(caminho: Path, linhas: list[dict[str, str]]) -> Path:
    from openpyxl import Workbook

    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Execucao"
    ws.append(list(COLUNAS_RELATORIO_NF))
    for linha in linhas:
        ws.append([linha.get(c, "") for c in COLUNAS_RELATORIO_NF])
    wb.save(caminho)
    return caminho


def gerar_relatorio_execucao(
    checkpoint_path: str | Path,
    *,
    destino_dir: str | Path,
    prefixo: str = "relatorio-classificacao-nf",
    formatos: tuple[str, ...] = ("csv", "xlsx"),
) -> dict[str, Any]:
    """Lê checkpoint e gera artefatos. Sem itens → CSV/XLSX só com cabeçalho."""
    ck = Checkpoint.carregar(checkpoint_path)
    linhas = [item_para_linha(i) for i in ck.itens.values()]
    out_dir = Path(destino_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    artefatos: dict[str, str] = {}

    if "csv" in formatos:
        artefatos["csv"] = str(_escrever_csv(out_dir / f"{prefixo}.csv", linhas))
    if "xlsx" in formatos:
        artefatos["xlsx"] = str(_escrever_xlsx(out_dir / f"{prefixo}.xlsx", linhas))

    logger.info(
        "[reporting] gerou %s linha(s) → %s",
        len(linhas),
        list(artefatos.values()),
    )
    return {
        "ok": True,
        "linhas": len(linhas),
        "artefatos": artefatos,
        "resumo": ck.resumo(),
    }


def gravar_controle_classificacao(
    checkpoint: Checkpoint | str | Path,
    *,
    destino: str | Path,
) -> Path:
    """Snapshot operacional ControleClassificacao.xlsx (schema Avaliação).

    Após coleta: só ERP/aliases. Após LYNN: enriquece com ``{stem}.json`` ao
    lado do PDF, se existir. Substitui o ficheiro destino.
    """
    if isinstance(checkpoint, Checkpoint):
        ck = checkpoint
    else:
        ck = Checkpoint.carregar(checkpoint)
    linhas = [item_para_linha_avaliacao(i) for i in ck.itens.values()]
    path = Path(destino)
    gravado = gravar_avaliacao_xlsx(path, linhas)
    logger.info(
        "[reporting] ControleClassificacao %s linha(s) cols=%s → %s",
        len(linhas),
        len(COLUNAS_AVALIACAO),
        gravado,
    )
    return gravado
