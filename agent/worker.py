"""Worker unificado — entrypoint único do agente Carol App RPA (Tezk42/FSB).

Pipeline (agent.pipeline.ESTAGIOS):

    preflight → vpn → pre_hooks → sessao_remota → login_erp
              → run_agente → post_hooks → cleanup

Contrato de saída: um envelope de dados com `ok`, `erro` (slug estável) e
`passos`. Uma corrida agendada roda sem ninguém olhando; o worker precisa
dizer *qual passo* falhou, não emitir um stack trace e morrer.

Uso:
    python -m agent.worker --dry-run --json
    python -m agent.worker --erp protheus --ate login
"""

from __future__ import annotations

import argparse
import json
import logging
import os
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

ESTAGIOS_CLI = ("preflight", "vpn", "sessao", "login", "fim")


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
        help="agente de negócio a executar (default: o do ERP ativo)",
    )
    p.add_argument("--ambiente", default="", help="ambiente do ERP (ex.: P|D)")

    p.add_argument("--sem-vpn", action="store_true", help="não estabelece nem verifica VPN")
    p.add_argument("--vpn-mode", default="", help="host|container (sobrepõe VPN_MODE)")

    p.add_argument("--dry-run", action="store_true", help="só preflight: valida config, sem UI/VPN")
    p.add_argument("--smoke", action="store_true", help="alias de --dry-run (preflight)")
    p.add_argument(
        "--ate", choices=ESTAGIOS_CLI, default="fim",
        help="para o pipeline após o estágio indicado (diagnóstico incremental)",
    )
    p.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    return p


# ---------------------------------------------------------------------------
# Estágios
# ---------------------------------------------------------------------------


def _estagio_vpn(result: dict[str, Any], *, sem_vpn: bool, vpn_mode: str) -> bool:
    if sem_vpn:
        registrar_passo(result, "vpn", ok=True, detalhe="ignorada (--sem-vpn)")
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


def executar_fluxo(
    *,
    agente: str,
    erp: str,
    runtime: str,
    tipo_sessao: str,
    sem_vpn: bool = False,
    vpn_mode: str = "",
    ate: str = "fim",
    kwargs_agente: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Executa o pipeline completo e devolve o envelope de resultado."""
    result = novo_resultado(agente)
    result["erp"] = erp
    result["runtime"] = runtime
    sessao = None
    surface = None

    try:
        # --- preflight ---
        relatorio = run_preflight(erp=erp, runtime=runtime, fluxo=agente)
        result["preflight"] = relatorio
        if not relatorio["ready_ui"]:
            falhos = [c["check"] for c in relatorio["checks"] if not c["ok"]]
            registrar_passo(result, "preflight", ok=False, detalhe=f"pendências: {falhos}")
            result["erro"] = "preflight_falhou"
            return result
        registrar_passo(result, "preflight", ok=True)
        if ate == "preflight":
            result["ok"] = True
            result["parcial"] = "preflight"
            return result

        # --- vpn ---
        if not _estagio_vpn(result, sem_vpn=sem_vpn, vpn_mode=vpn_mode):
            return result
        if ate == "vpn":
            result["ok"] = True
            result["parcial"] = "vpn"
            return result

        # Xvfb (Web Agent Electron) fica a cargo do entrypoint do container.

        # --- sessão remota ---
        sessao, surface = _abrir_sessao(result, tipo_sessao=tipo_sessao, erp=erp, runtime=runtime)
        if sessao is None:
            return result
        if ate == "sessao":
            result["ok"] = True
            result["parcial"] = "sessao"
            return result

        # --- login no ERP ---
        from agent.erp.factory import get_erp_agent

        agente_erp = get_erp_agent(surface, erp=erp)
        if not agente_erp.login():
            registrar_passo(result, "login_erp", ok=False, detalhe="autenticação recusada")
            result["erro"] = "login_erp_falhou"
            return result
        registrar_passo(result, "login_erp", ok=True)
        if ate == "login":
            result["ok"] = True
            result["parcial"] = "login"
            return result

        # --- rotina de negócio ---
        saida = agente_erp.run(**(kwargs_agente or {}))
        registrar_passo(result, "run_agente", ok=bool(saida.get("ok")), detalhe=str(saida.get("erro") or ""))
        result = fundir_resultado_agente(result, saida)
        return result

    except Exception as e:
        logger.error("[worker] erro não tratado: %s", e, exc_info=True)
        registrar_passo(result, "run_agente", ok=False, detalhe=str(e))
        result["ok"] = False
        result["erro"] = result.get("erro") or f"excecao: {type(e).__name__}"
        # A Surface é anexada para que o alerta capture a tela do momento da falha.
        result["_surface"] = surface
        return result

    finally:
        # Cleanup em ordem inversa, tolerante: cada peça é independente e uma
        # falha aqui não pode mascarar o resultado real da corrida.
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
        for chave in ("_vpn", "_vpn_do_agente"):
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
        agente = next((n for n, m in AGENTES.items() if m["erp"] == erp), "")
        if not agente:
            logger.error("nenhum fluxo registado para o ERP '%s'", erp)
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

    result = executar_fluxo(
        agente=agente,
        erp=erp,
        runtime=runtime,
        tipo_sessao=tipo_sessao,
        sem_vpn=args.sem_vpn,
        vpn_mode=args.vpn_mode,
        ate=args.ate,
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
