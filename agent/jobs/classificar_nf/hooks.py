"""Hooks do pipeline para o fluxo classificar_nf."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def pre_hook_classificar_nf(result: dict[str, Any]) -> dict[str, Any]:
    """Data-plane após VPN. Injeta fila_ui e checkpoint no envelope."""
    from agent import config
    from agent.domain.classificacao_nf.xlsx_loader import carregar_tabelas_depara_de_config
    from agent.integrations.fileshare import criar_fileshare_client
    from agent.integrations.lynn import criar_lynn_client
    from agent.integrations.protheus_api import criar_protheus_api_client
    from agent.jobs.classificar_nf.data_plane import executar_data_plane

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    corrida_id = f"classificar_nf-{stamp}"
    ck_dir = Path(config.CLASSIFICAR_NF_CHECKPOINT_DIR)
    ck_dir.mkdir(parents=True, exist_ok=True)
    ck_diario = ck_dir / f"checkpoint-{datetime.now().strftime('%Y%m%d')}.json"
    checkpoint_path = (
        Path(config.CLASSIFICAR_NF_CHECKPOINT_PATH)
        if config.CLASSIFICAR_NF_CHECKPOINT_PATH
        else ck_diario
    )

    from agent.jobs.classificar_nf.caminhos import caminhos_de_config, pasta_trabalho_pdf

    work_dir = pasta_trabalho_pdf()
    nivel_max = config.CLASSIFICAR_NF_NIVEL_MAX
    so_coleta = bool(result.get("_so_coleta"))
    controle_xlsx = (
        (config.CLASSIFICAR_NF_CONTROLE_XLSX or "").strip()
        or caminhos_de_config()["controle_xlsx"]
    )

    from agent.jobs.classificar_nf.lab_seed import clientes_e_tabelas_lab, modos_fake_ativos

    usar_seed = config.CLASSIFICAR_NF_LAB_SEED and modos_fake_ativos(
        protheus_mode=config.PROTHEUS_API_MODE,
        lynn_mode=config.LYNN_API_MODE,
        pdf_mode=config.PDF_SHARE_MODE,
    )
    if usar_seed:
        api, lynn, fileshare, tabelas = clientes_e_tabelas_lab()
        logger.info(
            "[pre_hook] CLASSIFICAR_NF_LAB_SEED ativo (API/LYNN fake; PDF=%s)",
            (config.PDF_SHARE_MODE or "fake").strip().lower(),
        )
    else:
        api = criar_protheus_api_client()
        lynn = criar_lynn_client()
        fileshare = criar_fileshare_client()
        tabelas = carregar_tabelas_depara_de_config()

    saida = executar_data_plane(
        api=api,
        lynn=lynn,
        fileshare=fileshare,
        tabelas=tabelas,
        checkpoint_path=checkpoint_path,
        work_dir=work_dir,
        nivel_max=nivel_max if nivel_max > 0 else None,
        forcar=config.CLASSIFICAR_NF_FORCAR,
        corrida_id=corrida_id,
        limite=config.CLASSIFICAR_NF_LIMITE,
        controle_xlsx=controle_xlsx,
        so_coleta=so_coleta,
    )
    result["_fila_ui"] = saida.get("fila_ui") or []
    result["_checkpoint_path"] = saida.get("checkpoint_path")
    result["resumo_data_plane"] = {
        "processados": saida.get("processados"),
        "ignorados": saida.get("ignorados"),
        "resumo": saida.get("resumo"),
        "elegiveis_restantes": saida.get("elegiveis_restantes"),
        "n_pendentes_protheus": saida.get("n_pendentes_protheus"),
        "n_sessao": saida.get("n_sessao"),
        "n_pdfs_lynn": saida.get("n_pdfs_lynn"),
        "n_pronto_ui": saida.get("n_pronto_ui"),
        "n_erros_sessao": saida.get("n_erros_sessao"),
    }
    artefatos = dict(result.get("artefatos") or {})
    artefatos["caminho_checkpoint"] = saida.get("checkpoint_path")
    if saida.get("caminho_controle"):
        artefatos["caminho_controle"] = saida.get("caminho_controle")
    result["artefatos"] = artefatos
    return saida


def post_hook_classificar_nf(result: dict[str, Any]) -> dict[str, Any]:
    """Gera relatório CSV/XLSX + e-mail fiscal (SMTP REPORT_*)."""
    from agent import config
    from agent.reporting.email_fiscal import enviar_relatorio_fiscal
    from agent.reporting.relatorio_nf import gerar_relatorio_execucao

    ck_path = result.get("_checkpoint_path") or (
        (result.get("artefatos") or {}).get("caminho_checkpoint")
    )
    out_dir = Path(config.CLASSIFICAR_NF_CHECKPOINT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # Resumo técnico (JSON) — auditoria interna
    resumo_json = out_dir / f"resumo-corrida-{stamp}.json"
    payload = {
        "ok": result.get("ok"),
        "erro": result.get("erro"),
        "agente": result.get("agente"),
        "resumo_data_plane": result.get("resumo_data_plane"),
        "checkpoint_path": ck_path,
        "classificadas": result.get("classificadas"),
        "falhas_ui": result.get("falhas_ui"),
        "ciclos_executados": result.get("ciclos_executados"),
        "observabilidade": result.get("observabilidade"),
        "passos": result.get("passos"),
    }
    resumo_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    artefatos = dict(result.get("artefatos") or {})
    artefatos["caminho_resumo_json"] = str(resumo_json)

    email_out: dict[str, Any] = {"ok": False, "skipped": True}
    caminho_csv = ""
    caminho_xlsx = ""

    if ck_path and Path(ck_path).is_file():
        gerado = gerar_relatorio_execucao(
            ck_path,
            destino_dir=out_dir,
            prefixo=f"relatorio-classificacao-nf-{stamp}",
        )
        caminho_csv = gerado.get("artefatos", {}).get("csv", "")
        caminho_xlsx = gerado.get("artefatos", {}).get("xlsx", "")
        if caminho_csv:
            artefatos["caminho_relatorio_csv"] = caminho_csv
        if caminho_xlsx:
            artefatos["caminho_relatorio"] = caminho_xlsx
            artefatos["caminho_relatorio_xlsx"] = caminho_xlsx

        anexos = [Path(p) for p in (caminho_xlsx, caminho_csv) if p]
        resumo = gerado.get("resumo") or {}
        obs = result.get("observabilidade") or {}
        sla = obs.get("sla") or {}
        body = (
            "Relatório de execução — classificação NFS TES 002 (Tezk42/FSB).\n\n"
            f"checkpoint: {ck_path}\n"
            f"itens: {resumo.get('total', 0)}\n"
            f"classificados: {resumo.get('Classificado', 0)}\n"
            f"nao_classificados: {resumo.get('Não Classificado', 0)}\n"
            f"pronto_ui: {resumo.get('Pronto para classificar', 0)}\n"
            f"fila_residual: {obs.get('fila_residual', '')}\n"
            f"duracao_s: {obs.get('duracao_s', '')}\n"
            f"sla_janela: {sla.get('janela', '')}\n"
            f"corrida_ok: {result.get('ok')}\n"
        )
        from agent.domain.classificacao_nf.status import StatusNf
        from agent.jobs.classificar_nf.lote import deve_enviar_email_fiscal

        resumo_dp = result.get("resumo_data_plane") or {}
        enviar = deve_enviar_email_fiscal(
            frequencia=config.REPORT_SMTP_FREQUENCIA,
            elegiveis_restantes=int(resumo_dp.get("elegiveis_restantes") or 0),
            pronto_ui=int(resumo.get(StatusNf.PRONTO_UI, 0) or 0),
        )
        if enviar:
            email_out = enviar_relatorio_fiscal(
                subject=f"[Tezk42] Relatório classificação NF — {stamp}",
                body=body,
                attachments=anexos,
            )
        else:
            email_out = {
                "ok": False,
                "skipped": True,
                "erro": "REPORT_SMTP_FREQUENCIA_esgotado",
            }
    else:
        logger.warning("[post_hook] checkpoint ausente — relatório gerencial não gerado")

    artefatos["email_fiscal"] = email_out
    result["artefatos"] = artefatos
    result["caminho_relatorio"] = artefatos.get("caminho_relatorio") or str(resumo_json)
    result["email_fiscal"] = email_out
    logger.info(
        "[post_hook] relatorio=%s email_skipped=%s email_erro=%s",
        result["caminho_relatorio"],
        email_out.get("skipped"),
        email_out.get("erro"),
    )
    return {
        "ok": True,
        "caminho_relatorio": result["caminho_relatorio"],
        "email": email_out,
    }
