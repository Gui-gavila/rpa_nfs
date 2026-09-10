"""Worker unificado — entrypoint único do agente Carol App RPA (Tezk42/FSB).

Pipeline (agent.pipeline.ESTAGIOS):

    preflight → vpn → pre_hooks → sessao_remota → login_erp
              → run_agente → post_hooks → cleanup

Modos de produção (`classificar_nf`):

    (default)                  pipeline completo (fases 1–9)
    --inicio-ate-planilha      preflight→vpn→data-plane→Controle.xlsx (sem UI/e-mail)
    --protheus-ate-fim         sessão→login→MATA103→post_hooks (fila do checkpoint)

Contrato de saída: envelope com `ok`, `erro` (slug estável) e `passos`.

Uso:
    python -m agent.worker --dry-run --json
    python -m agent.worker --fluxo classificar_nf --inicio-ate-planilha
    python -m agent.worker --fluxo classificar_nf --protheus-ate-fim
    python -m agent.worker --fluxo classificar_nf
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from agent import config
from agent.config import LOG_LEVEL
from agent.logging_setup import get_log_path, setup_run_logging
from agent.ops_alert import notify_run_failure
from agent.pipeline import (
    AGENTES,
    erp_do_agente,
    fundir_resultado_agente,
    normalize_agente,
    novo_resultado,
    registrar_passo,
)
from agent.preflight import run_preflight

logger = logging.getLogger(__name__)

MODO_COMPLETO = "completo"
MODO_INICIO_PLANILHA = "inicio_ate_planilha"
MODO_PROTHEUS_FIM = "protheus_ate_fim"
MODOS_PRODUCAO = (MODO_COMPLETO, MODO_INICIO_PLANILHA, MODO_PROTHEUS_FIM)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent.worker",
        description="Worker Carol App RPA — especialização Tezk42 (FSB) / Protheus",
    )
    p.add_argument("--erp", default="", help="protheus (default: ERP_TYPE)")
    p.add_argument("--runtime", default="", help="t2|t3 (default: RUNTIME_MODE)")
    p.add_argument("--sessao", default="", help="browser (default: derivado)")
    p.add_argument(
        "--fluxo",
        choices=sorted(AGENTES),
        default="",
        help="agente de negócio a executar (default: login)",
    )
    p.add_argument("--ambiente", default="", help="ambiente do ERP (ex.: P|D)")

    p.add_argument(
        "--vpn-mode", default="", help="host|container (sobrepõe VPN_MODE)"
    )

    p.add_argument(
        "--dry-run",
        action="store_true",
        help="só preflight: valida config, sem UI/VPN",
    )
    p.add_argument(
        "--smoke", action="store_true", help="alias de --dry-run (preflight)"
    )
    p.add_argument(
        "--inicio-ate-planilha",
        action="store_true",
        help=(
            "classificar_nf: fases 1–4 (coleta+LYNN+Controle.xlsx); "
            "sem sessão UI nem e-mail fiscal"
        ),
    )
    p.add_argument(
        "--protheus-ate-fim",
        action="store_true",
        help=(
            "classificar_nf: fases 5–9 a partir do checkpoint "
            "(PRONTO_UI -> MATA103 -> relatorio/e-mail); sem novo data-plane"
        ),
    )
    p.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    return p


def resolver_modo(
    *, inicio_ate_planilha: bool = False, protheus_ate_fim: bool = False
) -> str:
    """Resolve o modo de corrida. Flags mutuamente exclusivas."""
    if inicio_ate_planilha and protheus_ate_fim:
        raise ValueError("inicio_ate_planilha_e_protheus_ate_fim")
    if inicio_ate_planilha:
        return MODO_INICIO_PLANILHA
    if protheus_ate_fim:
        return MODO_PROTHEUS_FIM
    return MODO_COMPLETO


# ---------------------------------------------------------------------------
# Estágios
# ---------------------------------------------------------------------------


def _exige_ui(modo: str) -> bool:
    return modo in (MODO_COMPLETO, MODO_PROTHEUS_FIM)


def _caminho_checkpoint_padrao() -> Path:
    ck_dir = Path(config.CLASSIFICAR_NF_CHECKPOINT_DIR)
    if config.CLASSIFICAR_NF_CHECKPOINT_PATH:
        return Path(config.CLASSIFICAR_NF_CHECKPOINT_PATH)
    return ck_dir / f"checkpoint-{datetime.now().strftime('%Y%m%d')}.json"


def _estagio_vpn(result: dict[str, Any], *, sem_vpn: bool, vpn_mode: str) -> bool:
    if sem_vpn:
        registrar_passo(result, "vpn", ok=True, detalhe="ignorada (SEM_VPN)")
        return True

    from agent.vpn.factory import get_vpn

    # Lab Docker Desktop: WIREGUARD_DNS remove o resolver do Docker; o IP do
    # host (host.docker.internal) tem de ser memorizado antes do túnel.
    if config.WEB_AGENT_FORWARD_HOST:
        from agent.remote.web_agent import ancorar_destino_forward

        ancorar_destino_forward(config.WEB_AGENT_FORWARD_HOST)

    vpn = get_vpn(mode=vpn_mode or None)
    if vpn.is_connected():
        registrar_passo(result, "vpn", ok=True, detalhe="já conectada")
        result["_vpn"] = vpn
        return True

    if not vpn.connect():
        registrar_passo(result, "vpn", ok=False, detalhe="falha ao conectar")
        result["erro"] = "vpn_falhou"
        return False

    registrar_passo(result, "vpn", ok=True, detalhe="conectada pelo agente")
    result["_vpn"] = vpn
    # Só desconectamos o que nós conectamos — ver cleanup.
    result["_vpn_do_agente"] = True
    return True


def _estagio_pre_hooks(result: dict[str, Any], *, agente: str) -> bool:
    if agente != "classificar_nf":
        registrar_passo(result, "pre_hooks", ok=True, detalhe="noop")
        return True
    try:
        from agent.jobs.classificar_nf.hooks import pre_hook_classificar_nf

        result["_so_coleta"] = False
        saida = pre_hook_classificar_nf(result)
        ok = bool(saida.get("ok", True))
        detalhe = (
            f"processados={saida.get('processados')} "
            f"fila_ui={len(saida.get('fila_ui') or [])}"
        )
        registrar_passo(result, "pre_hooks", ok=ok, detalhe=detalhe)
        if not ok:
            result["erro"] = result.get("erro") or "pre_hooks_falhou"
        return ok
    except Exception as e:
        logger.error("[worker] pre_hooks falhou: %s", e, exc_info=True)
        registrar_passo(result, "pre_hooks", ok=False, detalhe=str(e))
        result["erro"] = f"pre_hooks_falhou: {type(e).__name__}"
        return False


def _estagio_fila_checkpoint(result: dict[str, Any], *, agente: str) -> bool:
    """Carrega PRONTO_UI da planilha viva (fallback: checkpoint)."""
    if agente != "classificar_nf":
        registrar_passo(result, "pre_hooks", ok=True, detalhe="noop")
        return True
    try:
        from agent.domain.classificacao_nf.status import StatusNf
        from agent.jobs.classificar_nf.caminhos import caminhos_de_config
        from agent.jobs.classificar_nf.checkpoint import Checkpoint
        from agent.reporting.controle_vivo import (
            carregar_indice,
            completar_data_vencimento,
            item_de_linha_controle,
        )

        ck_path = _caminho_checkpoint_padrao()
        controle = (config.CLASSIFICAR_NF_CONTROLE_XLSX or "").strip() or (
            caminhos_de_config().get("controle_xlsx") or ""
        )
        indice = carregar_indice(controle) if controle else {}
        ck = Checkpoint.carregar(ck_path) if ck_path.is_file() else None
        tabela_esp: list = []
        try:
            from agent.domain.classificacao_nf.xlsx_loader import (
                carregar_tabelas_depara_de_config,
            )

            tabela_esp = list(
                carregar_tabelas_depara_de_config().vencimento_especial or []
            )
        except Exception:
            tabela_esp = []

        fila: list[dict[str, Any]] = []
        if indice:
            for chave, linha in sorted(indice.items()):
                if (linha.get("STATUS") or "") != StatusNf.PRONTO_UI:
                    continue
                item = ck.obter(chave) if ck is not None else None
                if item is None:
                    item = item_de_linha_controle(linha)
                else:
                    from dataclasses import replace

                    item = replace(item, status=StatusNf.PRONTO_UI)
                item = completar_data_vencimento(item, tabela_especial=tabela_esp)
                fila.append(item.to_dict())
        if not fila and ck is not None:
            fila = [
                completar_data_vencimento(i, tabela_especial=tabela_esp).to_dict()
                for i in ck.fila_ui()
            ]
        if not fila and not indice and ck is None:
            registrar_passo(
                result,
                "pre_hooks",
                ok=False,
                detalhe="planilha e checkpoint ausentes",
            )
            result["erro"] = "checkpoint_ausente"
            return False

        limite = int(config.CLASSIFICAR_NF_LIMITE or 0)
        if limite > 0:
            fila = fila[:limite]
        result["_fila_ui"] = fila
        result["_checkpoint_path"] = str(ck_path)
        artefatos = dict(result.get("artefatos") or {})
        artefatos["caminho_checkpoint"] = str(ck_path)
        if controle:
            artefatos["caminho_controle"] = str(controle)
        result["artefatos"] = artefatos
        result["resumo_data_plane"] = {
            "processados": 0,
            "ignorados": 0,
            "resumo": ck.resumo() if ck else {},
            "elegiveis_restantes": 0,
            "n_pendentes_protheus": 0,
            "n_sessao": 0,
            "n_pdfs_lynn": 0,
            "n_pronto_ui": len(fila),
            "n_erros_sessao": 0,
            "origem": "planilha" if indice else "checkpoint",
        }
        if not fila:
            registrar_passo(
                result,
                "pre_hooks",
                ok=False,
                detalhe="fila_ui vazia (planilha/checkpoint)",
            )
            result["erro"] = "fila_ui_vazia"
            return False
        registrar_passo(
            result, "pre_hooks", ok=True, detalhe=f"planilha fila_ui={len(fila)}"
        )
        return True
    except Exception as e:
        logger.error("[worker] fila planilha/checkpoint falhou: %s", e, exc_info=True)
        registrar_passo(result, "pre_hooks", ok=False, detalhe=str(e))
        result["erro"] = f"checkpoint_falhou: {type(e).__name__}"
        return False


def _estagio_post_hooks(result: dict[str, Any], *, agente: str) -> None:
    if agente != "classificar_nf":
        registrar_passo(result, "post_hooks", ok=True, detalhe="noop")
        return
    try:
        from agent.jobs.classificar_nf.hooks import post_hook_classificar_nf

        saida = post_hook_classificar_nf(result)
        registrar_passo(
            result,
            "post_hooks",
            ok=bool(saida.get("ok", True)),
            detalhe=str(saida.get("caminho_relatorio") or ""),
        )
    except Exception as e:
        logger.warning("[worker] post_hooks falhou: %s", e)
        registrar_passo(result, "post_hooks", ok=False, detalhe=str(e))


def _abrir_sessao(
    result: dict[str, Any], *, tipo_sessao: str, erp: str, runtime: str
) -> tuple[Any, Any] | tuple[None, None]:
    """Abre a sessão de UI e devolve (sessão, surface)."""
    from agent.remote.factory import get_remote_session

    if tipo_sessao != "browser":
        registrar_passo(
            result, "sessao_remota", ok=False,
            detalhe=f"SESSION_TYPE={tipo_sessao} não suportado (use browser)",
        )
        result["erro"] = "sessao_remota_falhou"
        return None, None

    sessao = get_remote_session(session_type=tipo_sessao, erp=erp, runtime=runtime)
    if not sessao.connect():
        registrar_passo(result, "sessao_remota", ok=False, detalhe="browser não abriu")
        result["erro"] = "sessao_remota_falhou"
        return None, None

    surface = sessao.surface(resources_dir=config.PROTHEUS_RESOURCES_DIR)
    registrar_passo(result, "sessao_remota", ok=True, detalhe="browser")
    return sessao, surface


def _pronto_ui_checkpoint(result: dict[str, Any]) -> int:
    ck_path = result.get("_checkpoint_path") or (
        (result.get("artefatos") or {}).get("caminho_checkpoint")
    )
    if not ck_path or not Path(str(ck_path)).is_file():
        return 0
    try:
        from agent.domain.classificacao_nf.status import StatusNf
        from agent.jobs.classificar_nf.checkpoint import Checkpoint

        return int(
            Checkpoint.carregar(ck_path).resumo().get(StatusNf.PRONTO_UI, 0) or 0
        )
    except Exception:
        return 0


def _kwargs_run_agente(
    result: dict[str, Any], *, agente: str, kwargs_agente: dict[str, Any] | None
) -> dict[str, Any]:
    kwargs = dict(kwargs_agente or {})
    kwargs["fluxo"] = agente
    if "_fila_ui" in result:
        kwargs["fila_ui"] = result["_fila_ui"]
    ck = result.get("_checkpoint_path") or (
        (result.get("artefatos") or {}).get("caminho_checkpoint")
    )
    if ck:
        kwargs["checkpoint_path"] = ck
    return kwargs


def _acumular_contagens_ui(
    result: dict[str, Any], saida: dict[str, Any], *, classificadas: int, falhas: int
) -> tuple[int, int]:
    classificadas += int(saida.get("classificadas") or 0)
    falhas += int(saida.get("falhas_ui") or 0)
    result["classificadas"] = classificadas
    result["falhas_ui"] = falhas
    return classificadas, falhas


def _anexar_observabilidade(result: dict[str, Any]) -> None:
    """Duração, fila residual e janela SLA — visíveis no --json."""
    from agent.jobs.classificar_nf.lote import montar_observabilidade

    inicio = result.get("_inicio_mono")
    duracao = (time.monotonic() - float(inicio)) if inicio is not None else 0.0
    dp = result.get("resumo_data_plane") or {}
    result["observabilidade"] = montar_observabilidade(
        duracao_s=duracao,
        ciclos_executados=int(result.get("ciclos_executados") or 1),
        elegiveis_restantes=int(dp.get("elegiveis_restantes") or 0),
        pronto_ui=_pronto_ui_checkpoint(result),
        classificadas=int(result.get("classificadas") or 0),
        falhas_ui=int(result.get("falhas_ui") or 0),
        nivel_max=int(config.CLASSIFICAR_NF_NIVEL_MAX or 0),
        referencia=date.today(),
    )
    logger.info(
        "[worker] observabilidade duracao_s=%s fila_residual=%s sla=%s",
        result["observabilidade"].get("duracao_s"),
        result["observabilidade"].get("fila_residual"),
        (result["observabilidade"].get("sla") or {}).get("janela"),
    )


def _registrar_fim_sessao(result: dict[str, Any], *, agente: str) -> None:
    """Bloco de fecho no log diário (só classificação NF)."""
    if agente != "classificar_nf":
        return
    from agent.jobs.classificar_nf.lote import formatar_resumo_sessao, montar_resumo_sessao

    fim = datetime.now()
    inicio = result.get("_inicio_sessao")
    mono = result.get("_inicio_mono")
    duracao = (time.monotonic() - float(mono)) if mono is not None else 0.0
    dp = result.get("resumo_data_plane") or {}
    obs = result.get("observabilidade") or {}
    n_erros = int(dp.get("n_erros_sessao") or 0) + int(result.get("falhas_ui") or 0)
    pronto = dp.get("n_pronto_ui")
    if pronto is None:
        pronto = len(result.get("_fila_ui") or [])
    resumo = montar_resumo_sessao(
        n_pendentes_protheus=int(dp.get("n_pendentes_protheus") or 0),
        n_sessao=int(dp.get("n_sessao") or 0),
        n_pdfs_lynn=int(dp.get("n_pdfs_lynn") or 0),
        n_pronto_ui=int(pronto or 0),
        n_classificadas=int(result.get("classificadas") or 0),
        n_erros=n_erros,
        inicio=inicio if isinstance(inicio, datetime) else None,
        fim=fim,
        duracao_s=float(obs.get("duracao_s") or duracao),
    )
    result["resumo_sessao"] = resumo
    logger.info(
        "[sessao] Finalizando sessão de trabalho de classificação de notas. fim=%s",
        resumo["fim"],
    )
    for linha in formatar_resumo_sessao(resumo):
        logger.info("[sessao] %s", linha)


def executar_fluxo(
    *,
    agente: str,
    erp: str,
    runtime: str,
    tipo_sessao: str,
    sem_vpn: bool = False,
    vpn_mode: str = "",
    modo: str = MODO_COMPLETO,
    kwargs_agente: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Executa o pipeline e devolve o envelope de resultado."""
    if modo not in MODOS_PRODUCAO:
        modo = MODO_COMPLETO
    result = novo_resultado(agente)
    result["erp"] = erp
    result["runtime"] = runtime
    result["modo"] = modo
    result["_inicio_mono"] = time.monotonic()
    result["_inicio_sessao"] = datetime.now()
    log_atual = get_log_path()
    if log_atual is not None:
        result.setdefault("artefatos", {})["caminho_log"] = str(log_atual)
    if agente == "classificar_nf":
        logger.info(
            "[sessao] Iniciando sessão de trabalho de classificação de notas. inicio=%s modo=%s",
            result["_inicio_sessao"].strftime("%Y-%m-%d %H:%M:%S"),
            modo,
        )
    logger.info(
        "[worker] inicio fluxo=%s erp=%s runtime=%s modo=%s log=%s",
        agente,
        erp,
        runtime,
        modo,
        log_atual,
    )
    sessao = None
    surface = None

    try:
        relatorio = run_preflight(erp=erp, runtime=runtime, fluxo=agente)
        result["preflight"] = relatorio
        if (
            agente == "classificar_nf"
            and modo != MODO_PROTHEUS_FIM
            and not relatorio.get("ready_data", True)
        ):
            falhos = [c["check"] for c in relatorio["checks"] if not c["ok"]]
            registrar_passo(
                result, "preflight", ok=False, detalhe=f"data-plane: {falhos}"
            )
            result["erro"] = "preflight_data_falhou"
            return result
        if _exige_ui(modo) and not relatorio.get("ready_ui", False):
            falhos = [c["check"] for c in relatorio["checks"] if not c["ok"]]
            registrar_passo(result, "preflight", ok=False, detalhe=f"pendências: {falhos}")
            result["erro"] = "preflight_falhou"
            return result
        if agente != "classificar_nf" and not relatorio.get("ready_ui", False):
            falhos = [c["check"] for c in relatorio["checks"] if not c["ok"]]
            registrar_passo(result, "preflight", ok=False, detalhe=f"pendências: {falhos}")
            result["erro"] = "preflight_falhou"
            return result
        registrar_passo(result, "preflight", ok=True)

        if not _estagio_vpn(result, sem_vpn=sem_vpn, vpn_mode=vpn_mode):
            return result

        if modo == MODO_PROTHEUS_FIM:
            if not _estagio_fila_checkpoint(result, agente=agente):
                return result
        else:
            if not _estagio_pre_hooks(result, agente=agente):
                return result
            if modo == MODO_INICIO_PLANILHA:
                result["ok"] = True
                result["parcial"] = MODO_INICIO_PLANILHA
                try:
                    _anexar_observabilidade(result)
                except Exception as e:
                    logger.warning("[worker] observabilidade: %s", e)
                return result

        sessao, surface = _abrir_sessao(
            result, tipo_sessao=tipo_sessao, erp=erp, runtime=runtime
        )
        if sessao is None:
            return result

        from agent.erp.factory import get_erp_agent

        agente_erp = get_erp_agent(surface, erp=erp)
        if not agente_erp.login():
            registrar_passo(result, "login_erp", ok=False, detalhe="autenticação recusada")
            result["erro"] = "login_erp_falhou"
            return result
        registrar_passo(result, "login_erp", ok=True)

        kwargs = _kwargs_run_agente(
            result, agente=agente, kwargs_agente=kwargs_agente
        )
        saida = agente_erp.run(**kwargs)
        registrar_passo(
            result, "run_agente", ok=bool(saida.get("ok")), detalhe=str(saida.get("erro") or "")
        )
        result = fundir_resultado_agente(result, saida)
        classificadas_acc, falhas_acc = 0, 0
        ciclo = 1
        if agente == "classificar_nf":
            classificadas_acc, falhas_acc = _acumular_contagens_ui(
                result, saida, classificadas=0, falhas=0
            )
            ciclos_max = 1
            if modo == MODO_COMPLETO:
                ciclos_max = max(1, int(config.CLASSIFICAR_NF_CICLOS or 1))
            from agent.jobs.classificar_nf.lote import deve_repetir_ciclo

            while True:
                restantes = int(
                    (result.get("resumo_data_plane") or {}).get(
                        "elegiveis_restantes"
                    )
                    or 0
                )
                pronto_ui = _pronto_ui_checkpoint(result)
                if not result.get("ok"):
                    break
                if not deve_repetir_ciclo(
                    ciclo_atual=ciclo,
                    ciclos_max=ciclos_max,
                    elegiveis_restantes=restantes,
                    pronto_ui=pronto_ui,
                ):
                    break
                ciclo += 1
                logger.info(
                    "[worker] ciclo interno %s/%s restantes=%s pronto_ui=%s",
                    ciclo,
                    ciclos_max,
                    restantes,
                    pronto_ui,
                )
                try:
                    if sessao:
                        sessao.disconnect()
                except Exception as e:
                    logger.warning("[worker] ciclo: fechar sessão: %s", e)
                sessao = None
                surface = None
                if not _estagio_pre_hooks(result, agente=agente):
                    break
                if not (result.get("_fila_ui") or []):
                    logger.info("[worker] ciclo %s sem fila_ui — encerra", ciclo)
                    ciclo -= 1
                    break
                sessao, surface = _abrir_sessao(
                    result, tipo_sessao=tipo_sessao, erp=erp, runtime=runtime
                )
                if sessao is None:
                    break
                agente_erp = get_erp_agent(surface, erp=erp)
                if not agente_erp.login():
                    registrar_passo(
                        result, "login_erp", ok=False, detalhe="autenticação recusada"
                    )
                    result["erro"] = "login_erp_falhou"
                    result["ok"] = False
                    break
                registrar_passo(result, "login_erp", ok=True)
                kwargs = _kwargs_run_agente(
                    result, agente=agente, kwargs_agente=kwargs_agente
                )
                saida = agente_erp.run(**kwargs)
                registrar_passo(
                    result,
                    "run_agente",
                    ok=bool(saida.get("ok")),
                    detalhe=str(saida.get("erro") or ""),
                )
                result = fundir_resultado_agente(result, saida)
                classificadas_acc, falhas_acc = _acumular_contagens_ui(
                    result,
                    saida,
                    classificadas=classificadas_acc,
                    falhas=falhas_acc,
                )
            result["ciclos_executados"] = ciclo

        try:
            _anexar_observabilidade(result)
        except Exception as e:
            logger.warning("[worker] observabilidade: %s", e)
        _estagio_post_hooks(result, agente=agente)
        return result

    except Exception as e:
        logger.error("[worker] erro não tratado: %s", e, exc_info=True)
        registrar_passo(result, "run_agente", ok=False, detalhe=str(e))
        result["ok"] = False
        result["erro"] = result.get("erro") or f"excecao: {type(e).__name__}"
        result["_surface"] = surface
        return result

    finally:
        try:
            _anexar_observabilidade(result)
        except Exception as e:
            logger.warning("[worker] observabilidade: %s", e)
        try:
            _registrar_fim_sessao(result, agente=agente)
        except Exception as e:
            logger.warning("[worker] resumo sessao: %s", e)
        try:
            if sessao:
                sessao.disconnect()
        except Exception as e:
            logger.warning("[worker] cleanup sessao_remota: %s", e)

        vpn = result.get("_vpn")
        if vpn is not None and result.get("_vpn_do_agente"):
            try:
                vpn.disconnect()
                logger.info("[worker] VPN desconectada (foi o agente que conectou)")
            except Exception as e:
                logger.warning("[worker] cleanup vpn: %s", e)
        registrar_passo(result, "cleanup", ok=True)
        for chave in (
            "_vpn",
            "_vpn_do_agente",
            "_fila_ui",
            "_checkpoint_path",
            "_surface",
            "_inicio_mono",
            "_inicio_sessao",
        ):
            if chave == "_surface":
                continue
            result.pop(chave, None)



# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _emitir(result: dict[str, Any], *, como_json: bool) -> None:
    limpo = {k: v for k, v in result.items() if not k.startswith("_")}
    if como_json:
        print(json.dumps(limpo, ensure_ascii=False, indent=2, default=str))
        return
    logger.info("resultado ok=%s erro=%s", limpo.get("ok"), limpo.get("erro"))
    for passo in limpo.get("passos") or []:
        marca = "OK  " if passo["ok"] else "FALHA"
        logger.info("  [%s] %s %s", marca, passo["passo"], passo.get("detalhe") or "")
    if limpo.get("artefatos"):
        logger.info("artefatos: %s", limpo["artefatos"])


def main(argv: list[str] | None = None) -> int:
    log_path = setup_run_logging(level=LOG_LEVEL)
    args = build_parser().parse_args(argv)
    try:
        return _main_impl(args, log_path=log_path)
    except Exception as e:
        logger.exception("corrida abortada: %s", e)
        notify_run_failure(exc=e, log_path=get_log_path() or log_path)
        return 1


def _main_impl(args: argparse.Namespace, *, log_path: Path) -> int:
    runtime = config.normalize_runtime_mode(args.runtime or None)

    try:
        modo = resolver_modo(
            inicio_ate_planilha=bool(args.inicio_ate_planilha),
            protheus_ate_fim=bool(args.protheus_ate_fim),
        )
    except ValueError:
        logger.error(
            "use apenas um de --inicio-ate-planilha ou --protheus-ate-fim"
        )
        return 2

    # Fluxo e ERP se determinam mutuamente. Se só um for dado, o outro segue;
    # se ambos forem dados e discordarem, abortar antes de abrir sessão.
    if args.fluxo:
        agente = normalize_agente(args.fluxo)
        erp = config.normalize_erp_type(args.erp) if args.erp else erp_do_agente(agente)
        if erp_do_agente(agente) != erp:
            logger.error(
                "fluxo '%s' pertence ao ERP '%s', mas --erp pede '%s'",
                agente, erp_do_agente(agente), erp,
            )
            return 2
    else:
        erp = config.normalize_erp_type(args.erp or None)
        # Modos de classificação implícitos → classificar_nf; senão smoke login.
        if modo in (MODO_INICIO_PLANILHA, MODO_PROTHEUS_FIM):
            agente = "classificar_nf"
        elif "login" in AGENTES and AGENTES["login"]["erp"] == erp:
            agente = "login"
        else:
            agente = next((n for n, m in AGENTES.items() if m["erp"] == erp), "")
        if not agente:
            logger.error("nenhum fluxo registado para o ERP '%s'", erp)
            return 2

    if modo in (MODO_INICIO_PLANILHA, MODO_PROTHEUS_FIM) and agente != "classificar_nf":
        logger.error(
            "--inicio-ate-planilha / --protheus-ate-fim exigem --fluxo classificar_nf"
        )
        return 2

    if args.ambiente:
        os.environ["PROTHEUS_AMBIENTE_SERVIDOR"] = args.ambiente

    # --- preflight / smoke ---
    if args.dry_run or args.smoke:
        relatorio = run_preflight(erp=erp, runtime=runtime, fluxo=agente)
        relatorio["agente"] = agente
        _emitir(relatorio, como_json=args.json)
        return 0 if relatorio.get("ok") else 1

    tipo_sessao = config.resolve_session_type(
        erp=erp, runtime=runtime, session=args.sessao or None
    )

    sem_vpn = bool(getattr(config, "SEM_VPN", False))
    result = executar_fluxo(
        agente=agente,
        erp=erp,
        runtime=runtime,
        tipo_sessao=tipo_sessao,
        sem_vpn=sem_vpn,
        vpn_mode=args.vpn_mode,
        modo=modo,
    )
    _emitir(result, como_json=args.json)

    if not result.get("ok"):
        notify_run_failure(
            result=result, surface=result.get("_surface"), log_path=log_path,
            titulo=f"Carol {erp.title()}",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
