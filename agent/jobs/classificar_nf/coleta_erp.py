"""Coleta ERP + planilha viva ControleClassificacao.xlsx.

Ordem: SF1 (+ SA2/SM0 no client) → ValidarMudancaStatus → merge planilha
→ ColetarPDF (só se PDF_RECUPERADO ≠ Sim) → atualiza planilha/checkpoint.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent.domain.classificacao_nf.objeto_pdf import montar_ac9_codent_de_nota
from agent.domain.classificacao_nf.status import StatusNf
from agent.jobs.classificar_nf.checkpoint import (
    Checkpoint,
    ItemCheckpoint,
    chave_nf,
)
from agent.reporting.controle_vivo import (
    FLAG_NAO,
    FLAG_SIM,
    carregar_indice,
    eh_sim,
    salvar_indice,
    upsert_indice,
)
from agent.reporting.enriquecer_controle import agora_iso_local, mapear_linha_avaliacao

logger = logging.getLogger(__name__)

_STATUS_JA_TRATADO = (
    StatusNf.CLASSIFICADO,
    StatusNf.PRONTO_UI,
    StatusNf.NAO_CLASSIFICADO,
)


def item_de_coleta(erp: Any, *, acb_objeto: str = "") -> ItemCheckpoint:
    """Linha operacional a partir da NotaErp (lado ERP do CR)."""
    chave = chave_nf(
        filial_codigo=erp.filial_codigo,
        numero_nf=erp.numero_nf,
        codigo_fornecedor=erp.codigo_fornecedor,
    )
    emissao = erp.data_emissao.isoformat() if getattr(erp, "data_emissao", None) else ""
    entrada = erp.data_entrada.isoformat() if getattr(erp, "data_entrada", None) else ""
    valor = erp.valor_total
    valor_txt = "" if valor is None else str(valor)
    return ItemCheckpoint(
        chave=chave,
        filial_codigo=erp.filial_codigo or "",
        numero_nf=erp.numero_nf or "",
        codigo_fornecedor=erp.codigo_fornecedor or "",
        codigo_loja=getattr(erp, "codigo_loja", "") or "",
        nome_fornecedor=getattr(erp, "nome_fornecedor", "") or "",
        filial_nome=getattr(erp, "filial_nome", "") or "",
        cod_objeto=(acb_objeto or getattr(erp, "cod_objeto", "") or ""),
        nivel=int(getattr(erp, "nivel", 0) or 0),
        tipo_nf=getattr(erp, "tipo_nf", "") or "",
        serie_nf=getattr(erp, "serie_nf", "") or "",
        data_emissao_nf=emissao,
        data_entrada_nf=entrada,
        valor_total_nf=valor_txt,
        ac9_codent=getattr(erp, "cod_objeto", "") or "",
    )


def _linha_erp_para_controle(erp: Any, *, acb_objeto: str = "") -> dict[str, str]:
    item = item_de_coleta(erp, acb_objeto=acb_objeto)
    ops = {
        "FILIAL": item.filial_codigo,
        "COD_FILIAL": item.filial_codigo,
        "NOME_FILIAL": item.filial_nome,
        "COD_FORNECEDOR": item.codigo_fornecedor,
        "NOME_FORNECEDOR": item.nome_fornecedor,
        "COD_LOJA": item.codigo_loja,
        "NIVEL_PJ": str(item.nivel or ""),
        "NUMERO_NF": item.numero_nf,
        "DATA_EMISSAO_NF": item.data_emissao_nf,
        "VALOR_TOTAL_NF": item.valor_total_nf,
        "SERIE_NF": item.serie_nf,
        "SERIE_PDF": item.serie_nf,
        "COD_ENTIDADE": item.ac9_codent or item.cod_objeto,
        "COD_OBJETO": item.cod_objeto,
        "STATUS": item.status or "",
    }
    if acb_objeto:
        ops["PDF_RECUPERADO"] = FLAG_SIM
        ops["COD_OBJETO"] = acb_objeto
        ops["COD_ENTIDADE"] = item.ac9_codent or acb_objeto
    return mapear_linha_avaliacao(ops=ops)


def executar_coleta_erp(
    *,
    api: Any,
    checkpoint_path: str | Path,
    controle_xlsx: str | Path = "",
    nivel_max: int | None = None,
    forcar: bool = False,
    corrida_id: str = "",
    limite: int = 0,
) -> dict[str, Any]:
    """Coleta + planilha viva. Devolve NFs candidatas ao data-plane (Lynn)."""
    ck = Checkpoint.carregar(checkpoint_path, corrida_id=corrida_id)
    if corrida_id:
        ck.corrida_id = corrida_id

    controle_path = Path(controle_xlsx) if controle_xlsx else None
    indice = carregar_indice(controle_path) if controle_path else {}

    pendentes = api.listar_nfs_tes002_pendentes(nivel_max=nivel_max)
    leftover = (
        []
        if forcar
        else [i for i in ck.itens.values() if i.status == StatusNf.PRONTO_UI]
    )
    vagas = None
    if limite and limite > 0:
        vagas = max(0, limite - len(leftover))

    consultar_status = getattr(api, "status_ainda_pendente", None)
    consultar_pdf = getattr(api, "consultar_acb_objeto", None)
    candidatos: list[Any] = []
    processados = 0
    ignorados = 0

    # --- A: SF1 + ValidarMudancaStatus → merge planilha (sem ColetarPDF) ---
    for erp in pendentes:
        chave = chave_nf(
            filial_codigo=erp.filial_codigo,
            numero_nf=erp.numero_nf,
            codigo_fornecedor=erp.codigo_fornecedor,
        )
        existente = ck.obter(chave)
        linha_plan = indice.get(chave)
        if (
            existente is not None
            and not forcar
            and existente.status in _STATUS_JA_TRATADO
        ):
            ignorados += 1
            continue
        if (
            linha_plan
            and not forcar
            and (linha_plan.get("STATUS") or "") in _STATUS_JA_TRATADO
            and eh_sim(linha_plan.get("LYNN_PROCESSADO"))
        ):
            ignorados += 1
            continue
        if vagas is not None and processados >= vagas:
            break

        if callable(consultar_status):
            try:
                ainda = consultar_status(
                    filial_codigo=erp.filial_codigo,
                    numero_nf=erp.numero_nf,
                    codigo_fornecedor=erp.codigo_fornecedor,
                    codigo_loja=getattr(erp, "codigo_loja", None) or "01",
                    serie_nf=getattr(erp, "serie_nf", None) or "GOV",
                )
            except Exception:
                logger.warning(
                    "[coleta_erp] ValidarMudancaStatus falhou %s — segue na lista",
                    chave,
                )
                ainda = True
            if not ainda:
                ignorados += 1
                logger.info(
                    "[coleta_erp] F1_STATUS fora do filtro pendente — fora da lista %s",
                    chave,
                )
                continue

        # Merge ERP/SA2/SM0 só em células vazias (planilha manda se já preenchida).
        upsert_indice(indice, _linha_erp_para_controle(erp), forcar=())
        candidatos.append(erp)
        processados += 1

    if controle_path and indice:
        salvar_indice(controle_path, indice)

    # --- B: ColetarPDF só se PDF_RECUPERADO ≠ Sim ---
    notas: list[Any] = []
    for erp in candidatos:
        chave = chave_nf(
            filial_codigo=erp.filial_codigo,
            numero_nf=erp.numero_nf,
            codigo_fornecedor=erp.codigo_fornecedor,
        )
        linha = indice.get(chave) or {}
        existente_ck = ck.obter(chave)
        nome_pdf = (existente_ck.cod_objeto if existente_ck else "") or ""

        if eh_sim(linha.get("PDF_RECUPERADO")) and nome_pdf and not forcar:
            logger.info("[coleta_erp] PDF já recuperado — skip ColetarPDF %s", chave)
        elif callable(consultar_pdf):
            codent = (getattr(erp, "cod_objeto", None) or "").strip()
            if not codent:
                try:
                    codent = montar_ac9_codent_de_nota(erp)
                except Exception:
                    codent = ""
            filial = (erp.filial_codigo or "").strip()
            nome_pdf = ""
            if filial and codent:
                try:
                    nome_pdf = (
                        consultar_pdf(filial=filial, ac9_codent=codent) or ""
                    ).strip()
                except Exception:
                    logger.warning("[coleta_erp] ColetarPDF falhou %s", chave)
            patch: dict[str, str] = {
                **_linha_erp_para_controle(erp, acb_objeto=nome_pdf),
                "PDF_RECUPERADO": FLAG_SIM if nome_pdf else FLAG_NAO,
                "COD_ENTIDADE": codent or (linha.get("COD_ENTIDADE") or ""),
            }
            # ENTRADA = agora na 1ª recuperação bem-sucedida (merge não sobrescreve).
            if nome_pdf and not (linha.get("TIMESTAMP ENTRADA") or "").strip():
                patch["TIMESTAMP ENTRADA"] = agora_iso_local()
            upsert_indice(
                indice,
                patch,
                forcar=("PDF_RECUPERADO", "COD_ENTIDADE"),
            )
        elif not eh_sim(linha.get("PDF_RECUPERADO")):
            upsert_indice(
                indice,
                {**linha, "PDF_RECUPERADO": FLAG_NAO},
                forcar=("PDF_RECUPERADO",),
            )

        ck.upsert(item_de_coleta(erp, acb_objeto=nome_pdf))
        extras = dict(getattr(erp, "extras", None) or {})
        extras["acb_objeto"] = nome_pdf
        logger.info(
            "[coleta_erp] NF %s pdf_recuperado=%s acb=%s",
            chave,
            (indice.get(chave) or {}).get("PDF_RECUPERADO"),
            nome_pdf or "(vazio)",
        )
        try:
            from dataclasses import replace

            notas.append(replace(erp, extras=extras))
        except TypeError:
            notas.append(erp)

    caminho_ck = ck.salvar()
    caminho_xlsx = ""
    if controle_path:
        caminho_xlsx = str(salvar_indice(controle_path, indice))

    logger.info(
        "[coleta_erp] processados=%s ignorados=%s controle=%s",
        processados,
        ignorados,
        caminho_xlsx or "(omitido)",
    )
    return {
        "ok": True,
        "checkpoint_path": str(caminho_ck),
        "caminho_controle": caminho_xlsx,
        "processados": processados,
        "ignorados": ignorados,
        "notas": notas,
        "pendentes_sf1": pendentes,
        "resumo": ck.resumo(),
        "_indice_controle": indice,
    }
