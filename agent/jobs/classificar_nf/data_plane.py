"""Data-plane: API → PDF → LYNN → domínio → checkpoint (sem UI)."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from agent.domain.classificacao_nf.deparas import TabelasDepara
from agent.domain.classificacao_nf.objeto_pdf import (
    candidatos_nomes_pdf,
    montar_ac9_codent_de_nota,
)
from agent.domain.classificacao_nf.preparar import preparar_classificacao
from agent.domain.classificacao_nf.status import MOTIVOS, StatusNf
from agent.jobs.classificar_nf.caminhos import (
    gravar_resposta_lynn,
    mover_pdf_para_processadas,
)
from agent.jobs.classificar_nf.checkpoint import (
    Checkpoint,
    ItemCheckpoint,
    chave_nf,
)

logger = logging.getLogger(__name__)

_STATUS_DATA_FECHADO = (
    StatusNf.CLASSIFICADO,
    StatusNf.PRONTO_UI,
    StatusNf.NAO_CLASSIFICADO,
)


def _fechado_no_data_plane(item: ItemCheckpoint | None, *, forcar: bool) -> bool:
    """True se a NF já passou pelo data-plane e não deve ir de novo ao LYNN."""
    if forcar or item is None:
        return False
    return item.status in _STATUS_DATA_FECHADO


def _contar_elegiveis_restantes(pendentes: list[Any], ck: Checkpoint) -> int:
    """NFs da lista SF1 que ainda não fecharam o data-plane (próximo worker)."""
    n = 0
    for erp in pendentes:
        chave = chave_nf(
            filial_codigo=erp.filial_codigo,
            numero_nf=erp.numero_nf,
            codigo_fornecedor=erp.codigo_fornecedor,
        )
        if not _fechado_no_data_plane(ck.obter(chave), forcar=False):
            n += 1
    return n


def _montar_fila_ui_bloco(
    ck: Checkpoint,
    *,
    leftover: list[ItemCheckpoint],
    limite: int,
) -> list[dict[str, Any]]:
    """Bloco desta corrida: leftover PRONTO_UI primeiro, depois as novas do lote."""
    chaves_leftover = {i.chave for i in leftover}
    novas = [
        i
        for i in ck.itens.values()
        if i.status == StatusNf.PRONTO_UI and i.chave not in chaves_leftover
    ]
    bloco = [*leftover, *novas]
    if limite and limite > 0:
        bloco = bloco[:limite]
    return [i.to_dict() for i in bloco]


def _item_de_prep(
    *,
    chave: str,
    erp: Any,
    prep: Any,
    pdf_path: str | None,
    pdf: Any | None = None,
) -> ItemCheckpoint:
    venc = prep.data_vencimento.isoformat() if prep.data_vencimento else None
    impostos = getattr(pdf, "impostos", None) if pdf is not None else None
    return ItemCheckpoint(
        chave=chave,
        filial_codigo=erp.filial_codigo,
        numero_nf=erp.numero_nf,
        codigo_fornecedor=erp.codigo_fornecedor,
        codigo_loja=getattr(erp, "codigo_loja", "") or "",
        nome_fornecedor=getattr(erp, "nome_fornecedor", "") or "",
        filial_nome=getattr(erp, "filial_nome", "") or "",
        cod_objeto=_cod_objeto_pdf(erp),
        ac9_codent=getattr(erp, "cod_objeto", "") or "",
        nivel=erp.nivel,
        tipo_nf=getattr(erp, "tipo_nf", "") or "",
        serie_nf=getattr(erp, "serie_nf", "") or "",
        data_emissao_nf=erp.data_emissao.isoformat() if getattr(erp, "data_emissao", None) else "",
        data_entrada_nf=erp.data_entrada.isoformat() if getattr(erp, "data_entrada", None) else "",
        valor_total_nf=str(erp.valor_total) if getattr(erp, "valor_total", None) is not None else "",
        status=prep.status,
        motivo=prep.motivo,
        codigo_servico=prep.codigo_servico,
        natureza_despesa=prep.natureza_despesa,
        natureza_rendimento=prep.natureza_rendimento,
        codigo_retencao=prep.codigo_retencao,
        data_vencimento=venc,
        pdf_path=pdf_path,
        issqn=str(getattr(impostos, "issqn", "0") if impostos else "0"),
        irrf=str(getattr(impostos, "irrf", "0") if impostos else "0"),
        pis=str(getattr(impostos, "pis", "0") if impostos else "0"),
        cofins=str(getattr(impostos, "cofins", "0") if impostos else "0"),
        csll=str(getattr(impostos, "csll", "0") if impostos else "0"),
    )


def executar_data_plane(
    *,
    api: Any,
    lynn: Any,
    fileshare: Any,
    tabelas: TabelasDepara,
    checkpoint_path: str | Path,
    work_dir: str | Path,
    nivel_max: int | None = None,
    referencia: date | None = None,
    forcar: bool = False,
    corrida_id: str = "",
    limite: int = 0,
    controle_xlsx: str | Path = "",
    so_coleta: bool = False,
) -> dict[str, Any]:
    """Processa pendentes. Falha de uma NF não aborta o lote."""
    ref = referencia or date.today()
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    from agent.jobs.classificar_nf.coleta_erp import executar_coleta_erp, item_de_coleta

    leftover_antes = Checkpoint.carregar(checkpoint_path).itens
    leftover = [i for i in leftover_antes.values() if i.status == StatusNf.PRONTO_UI]
    vagas_lynn = None
    if limite and limite > 0:
        reservados = 0 if forcar else len(leftover)
        vagas_lynn = max(0, limite - reservados)

    coleta = executar_coleta_erp(
        api=api,
        checkpoint_path=checkpoint_path,
        controle_xlsx=controle_xlsx,
        nivel_max=nivel_max,
        forcar=forcar,
        corrida_id=corrida_id,
        limite=limite,
    )
    ck = Checkpoint.carregar(coleta["checkpoint_path"], corrida_id=corrida_id)
    if corrida_id:
        ck.corrida_id = corrida_id

    if so_coleta:
        logger.info("[data_plane] so_coleta — sem LYNN/fileshare")
        sessao = _contadores_sessao(
            coleta, n_pdfs_lynn=0, n_erros=0, fila=[]
        )
        return {
            "ok": True,
            "checkpoint_path": coleta["checkpoint_path"],
            "caminho_controle": coleta.get("caminho_controle") or "",
            "resumo": coleta.get("resumo") or ck.resumo(),
            "processados": coleta.get("processados") or 0,
            "ignorados": coleta.get("ignorados") or 0,
            "elegiveis_restantes": _contar_elegiveis_restantes(
                coleta.get("pendentes_sf1") or [], ck
            ),
            "fila_ui": [],
            **sessao,
        }

    pendentes = coleta.get("notas") or []
    processados = 0
    ignorados = int(coleta.get("ignorados") or 0)
    n_pdfs_lynn = 0
    n_erros = 0

    from agent.reporting.controle_vivo import (
        CAMPOS_AVANCO,
        FLAG_SIM,
        carregar_indice,
        eh_sim,
        salvar_indice,
        upsert_indice,
    )
    from agent.reporting.relatorio_nf import item_para_linha_avaliacao

    indice = dict(coleta.get("_indice_controle") or {})
    if controle_xlsx and not indice:
        indice = carregar_indice(controle_xlsx)

    for erp in pendentes:
        chave = chave_nf(
            filial_codigo=erp.filial_codigo,
            numero_nf=erp.numero_nf,
            codigo_fornecedor=erp.codigo_fornecedor,
        )
        existente = ck.obter(chave)
        linha_plan = indice.get(chave) or {}
        if not forcar and eh_sim(linha_plan.get("LYNN_PROCESSADO")):
            ignorados += 1
            logger.info("[data_plane] Lynn já processado — skip %s", chave)
            if existente is None and linha_plan.get("STATUS") == StatusNf.PRONTO_UI:
                # Espelha no ck para fila_ui / UI
                ck.upsert(item_de_coleta(erp))
            continue
        if _fechado_no_data_plane(existente, forcar=forcar):
            ignorados += 1
            continue
        if vagas_lynn is not None and processados >= vagas_lynn:
            break

        pdf_path: str | None = None
        origem_pdf: Path | None = None
        payload_lynn: Any = None
        stem = chave.replace("|", "_")
        try:
            acb_objeto = _acb_objeto_de_erp(erp) or _consultar_acb_objeto(api, erp)
            origem_pdf = _origem_pdf(
                fileshare,
                erp,
                acb_objeto=acb_objeto,
                destino=work / f"{stem}.pdf",
            )
            origem_pdf = _garantir_pdf_puro(origem_pdf)
            pdf = lynn.extrair_nf(origem_pdf)
            n_pdfs_lynn += 1
            payload_lynn = _payload_resposta_lynn(pdf)
            prep = preparar_classificacao(erp, pdf, tabelas, referencia=ref)
            pdf_path = _arquivar_apos_lynn(
                origem_pdf, work, stem=stem, payload=payload_lynn
            )
            item = _item_de_prep(
                chave=chave, erp=erp, prep=prep, pdf_path=pdf_path, pdf=pdf
            )
            ck.upsert(item)
            if controle_xlsx:
                status_lynn = ""
                clf = getattr(pdf, "classificacao", None)
                if clf is not None:
                    status_lynn = str(getattr(clf, "status", "") or "")
                linha_av = item_para_linha_avaliacao(item)
                linha_av["LYNN_PROCESSADO"] = FLAG_SIM
                linha_av["STATUS_LYNN"] = status_lynn or linha_av.get("STATUS_LYNN", "")
                linha_av["PDF_RECUPERADO"] = FLAG_SIM
                linha_av["STATUS"] = prep.status or ""
                if prep.motivo:
                    linha_av["MOTIVO"] = prep.motivo
                upsert_indice(
                    indice,
                    linha_av,
                    forcar=list(CAMPOS_AVANCO),
                )
            if prep.status == StatusNf.NAO_CLASSIFICADO:
                n_erros += 1
            logger.info(
                "[data_plane] NF %s status=%s pdf=%s",
                chave,
                prep.status,
                pdf_path,
            )
        except Exception as e:
            logger.warning("[data_plane] NF %s falhou: %s", chave, e)
            n_erros += 1
            if payload_lynn is None:
                payload_lynn = {
                    "ok": False,
                    "erro": type(e).__name__,
                    "mensagem": str(e),
                }
            pdf_path = _arquivar_apos_lynn(
                origem_pdf, work, stem=stem, payload=payload_lynn
            )
            from dataclasses import replace

            base = existente or item_de_coleta(erp)
            item_err = replace(
                base,
                status=StatusNf.NAO_CLASSIFICADO,
                motivo=MOTIVOS.campo_nao_coletado(
                    f"processamento ({type(e).__name__})"
                ),
                pdf_path=pdf_path or base.pdf_path,
            )
            ck.upsert(item_err)
            if controle_xlsx:
                upsert_indice(
                    indice,
                    {
                        **item_para_linha_avaliacao(item_err),
                        "LYNN_PROCESSADO": FLAG_SIM,
                        "STATUS_LYNN": type(e).__name__,
                        "STATUS": StatusNf.NAO_CLASSIFICADO,
                    },
                    forcar=list(CAMPOS_AVANCO),
                )
        processados += 1
        ck.salvar()

    caminho = ck.salvar()
    caminho_controle = str(coleta.get("caminho_controle") or "")
    if controle_xlsx:
        caminho_controle = str(salvar_indice(controle_xlsx, indice))
    # Fila UI: só Pronto para classificar (checkpoint espelhado da planilha).
    if controle_xlsx and indice:
        for chave, linha in indice.items():
            if (linha.get("STATUS") or "") != StatusNf.PRONTO_UI:
                continue
            if ck.obter(chave) is None:
                continue
        # Alinha status do ck com planilha para leftover
        for item in list(ck.itens.values()):
            lp = indice.get(item.chave)
            if lp and lp.get("STATUS"):
                from dataclasses import replace

                ck.upsert(replace(item, status=lp["STATUS"], motivo=lp.get("MOTIVO") or item.motivo))
        ck.salvar()
    fila = _montar_fila_ui_bloco(ck, leftover=leftover, limite=limite)
    # Filtra estritamente Pronto (defesa)
    fila = [x for x in fila if (x.get("status") or "") == StatusNf.PRONTO_UI]
    resumo = ck.resumo()
    elegiveis_restantes = _contar_elegiveis_restantes(
        coleta.get("pendentes_sf1") or pendentes, ck
    )
    sessao = _contadores_sessao(
        coleta, n_pdfs_lynn=n_pdfs_lynn, n_erros=n_erros, fila=fila
    )
    logger.info(
        "[data_plane] processados=%s ignorados=%s restantes=%s lynn=%s erros=%s resumo=%s checkpoint=%s",
        processados,
        ignorados,
        elegiveis_restantes,
        n_pdfs_lynn,
        n_erros,
        resumo,
        caminho,
    )
    return {
        "ok": True,
        "checkpoint_path": str(caminho),
        "caminho_controle": caminho_controle,
        "resumo": resumo,
        "processados": processados,
        "ignorados": ignorados,
        "elegiveis_restantes": elegiveis_restantes,
        "fila_ui": fila,
        **sessao,
    }


def _contadores_sessao(
    coleta: dict[str, Any],
    *,
    n_pdfs_lynn: int,
    n_erros: int,
    fila: list[Any],
) -> dict[str, int]:
    """Números desta corrida para o resumo de sessão no log."""
    return {
        "n_pendentes_protheus": len(coleta.get("pendentes_sf1") or []),
        "n_sessao": int(coleta.get("processados") or 0),
        "n_pdfs_lynn": int(n_pdfs_lynn or 0),
        "n_pronto_ui": len(fila or []),
        "n_erros_sessao": int(n_erros or 0),
    }


def _acb_objeto_de_erp(erp: Any) -> str:
    extras = getattr(erp, "extras", None) or {}
    if isinstance(extras, dict):
        return str(extras.get("acb_objeto") or "").strip()
    return ""


def _cod_objeto_pdf(erp: Any) -> str:
    return _acb_objeto_de_erp(erp) or (getattr(erp, "cod_objeto", None) or "")


def _consultar_acb_objeto(api: Any, erp: Any) -> str:
    consultar = getattr(api, "consultar_acb_objeto", None)
    if not callable(consultar):
        return ""
    filial = (getattr(erp, "filial_codigo", None) or "").strip()
    codent = (getattr(erp, "cod_objeto", None) or "").strip()
    if not codent:
        serie = (getattr(erp, "serie_nf", None) or "").strip()
        loja = (getattr(erp, "codigo_loja", None) or "").strip()
        if serie and loja:
            codent = montar_ac9_codent_de_nota(erp)
    if not filial or not codent:
        return ""
    try:
        return (consultar(filial=filial, ac9_codent=codent) or "").strip()
    except Exception:
        logger.warning("[data_plane] ColetarPDF falhou filial=%s", filial)
        return ""


def _arquivar_apos_lynn(
    pdf_path: str | Path | None,
    work_dir: Path,
    *,
    stem: str,
    payload: Any | None,
) -> str | None:
    """Move o PDF da inbox para 02 (nome-stem) e grava o JSON do LYNN ao lado."""
    if pdf_path is None:
        return None
    origem = Path(pdf_path)
    if not origem.is_file():
        return None
    alvo: Path = origem
    try:
        novo = mover_pdf_para_processadas(
            origem, work_dir=work_dir, nome_destino=f"{stem}.pdf"
        )
        if novo is not None:
            alvo = novo
    except OSError as e:
        logger.warning("[data_plane] move 01→02 falhou %s: %s", origem, e)
    if payload is not None:
        try:
            json_path = gravar_resposta_lynn(alvo, payload)
            logger.info("[data_plane] json_lynn=%s", json_path)
        except OSError as e:
            logger.warning("[data_plane] JSON LYNN falhou %s: %s", alvo, e)
    return str(alvo)


def _origem_pdf(
    fileshare: Any,
    erp: Any,
    *,
    acb_objeto: str,
    destino: Path,
) -> Path:
    """Garante PDF na inbox (stage TI se configurado) e localiza para o LYNN."""
    candidatos = candidatos_nomes_pdf(erp, acb_objeto=acb_objeto)
    cod = (getattr(erp, "cod_objeto", None) or "") or acb_objeto
    _stage_pdf_ti_para_inbox(
        inbox=destino.parent,
        cod_objeto=str(cod or ""),
        candidatos=candidatos,
    )
    localizar = getattr(fileshare, "localizar_pdf", None)
    if callable(localizar):
        return Path(localizar(erp.cod_objeto, candidatos=candidatos))
    return Path(fileshare.obter_pdf(erp.cod_objeto, destino, candidatos=candidatos))


def _stage_pdf_ti_para_inbox(
    *,
    inbox: Path,
    cod_objeto: str,
    candidatos: list[str],
) -> Path | None:
    """Copia da pasta de rede TI (`PDF_SHARE_SOURCE`) para a inbox, se configurado."""
    from agent import config

    fonte = (getattr(config, "PDF_SHARE_SOURCE", "") or "").strip()
    if not fonte:
        return None
    from agent.jobs.classificar_nf.stage_pdf import garantir_pdf_na_inbox

    try:
        subdirs_raw = (getattr(config, "PDF_SHARE_SOURCE_SUBDIRS", "") or "").strip()
        subdirs = [p.strip() for p in subdirs_raw.split(",") if p.strip()]
        return garantir_pdf_na_inbox(
            origem_root=fonte,
            inbox=inbox,
            cod_objeto=cod_objeto,
            candidatos=candidatos,
            subdirs=subdirs,
        )
    except FileNotFoundError:
        logger.warning(
            "[data_plane] PDF ausente na origem TI %s (candidatos=%s)",
            fonte,
            candidatos[:3],
        )
        return None


def _garantir_pdf_puro(path: Path) -> Path:
    """Se o ficheiro for POST multipart, recorta o PDF interno in-place."""
    from agent.integrations.fileshare.local import _desembrulhar_pdf_se_multipart

    bruto = path.read_bytes()
    payload = _desembrulhar_pdf_se_multipart(bruto)
    if payload != bruto:
        path.write_bytes(payload)
        logger.info("[data_plane] PDF interno extraído in-place %s", path)
    return path


def _payload_resposta_lynn(pdf: Any) -> dict[str, Any]:
    extras = getattr(pdf, "extras", None) or {}
    if isinstance(extras, dict):
        raw = extras.get("_resposta_lynn")
        if isinstance(raw, dict):
            return raw
    clf = getattr(pdf, "classificacao", None)
    classificacao = None
    if clf is not None:
        classificacao = {
            "STATUS": getattr(clf, "status", None),
            "MOTIVO": getattr(clf, "motivo", None),
            "NATUREZA_DESPESA": getattr(clf, "natureza_despesa", None),
            "NATUREZA_RENDIMENTO": getattr(clf, "natureza_rendimento", None),
            "COD_TRIBUTACAO": getattr(clf, "cod_tributacao", None),
            "COD_RETENCAO_IRRF": getattr(clf, "cod_retencao_irrf", None),
            "COD_RETENCAO_PCC": getattr(clf, "cod_retencao_pcc", None),
            "LAYOUT": getattr(clf, "layout", None),
            "MEI": getattr(clf, "mei", None),
        }
    limpos = {
        k: v
        for k, v in (extras.items() if isinstance(extras, dict) else [])
        if k != "_resposta_lynn"
    }
    return {
        "extracao": {
            "numero_nf": getattr(pdf, "numero_nf", ""),
            "cnpj_prestador": getattr(pdf, "cnpj_prestador", ""),
            "cnpj_tomador": getattr(pdf, "cnpj_tomador", ""),
            "codigo_servico": getattr(pdf, "codigo_servico", ""),
            "valor_total": str(getattr(pdf, "valor_total", "")),
            "tipo_nf": getattr(pdf, "tipo_nf", ""),
            "data_emissao": str(getattr(pdf, "data_emissao", "") or ""),
            **limpos,
        },
        "classificacao": classificacao,
    }
