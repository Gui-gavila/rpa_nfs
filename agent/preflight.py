"""Preflight — valida configuração e alcance antes de gastar UI, VPN ou sessão.

Um agente RPA falha caro: se a credencial está vazia ou a pasta de rede não
responde, descobrir isso depois de subir VPN e navegar várias telas custa
minutos e deixa sessões penduradas. O preflight responde antes de tudo.

Devolve um relatório de dados, não exceções:

    {ok, erp, runtime, ready_ui, ready_edi, checks: [{check, ok, detail}], cwd}

`ready_*` são o que decide se o fluxo pode seguir; `checks` é o detalhe para o
operador. Segredos nunca aparecem — só "(definido)" ou "(vazio)".
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent import config


def _check(label: str, passou: bool, detalhe: str = "") -> dict[str, Any]:
    return {"check": label, "ok": bool(passou), "detail": detalhe}


def _presenca(valor: str) -> str:
    """Reporta presença sem vazar o valor."""
    return "(definido)" if valor else "(vazio)"


# Variáveis cujo valor é segredo e não deve aparecer no relatório.
_SEGREDOS = ("PASSWORD", "SENHA", "OTP", "KEY", "TOKEN", "SECRET")


def _checks_comuns(erp: str, runtime: str) -> list[dict[str, Any]]:
    from agent.vpn.factory import TIPOS_SUPORTADOS, requisitos_do_tipo

    modo_vpn = config.normalize_vpn_mode()
    tipo_vpn = (config.VPN_TYPE or "").strip()

    checks = [
        _check("erp_type", True, erp),
        _check("runtime_mode", True, runtime),
        _check("vpn_mode", True, modo_vpn),
        _check(
            "vpn_type",
            tipo_vpn.upper() in TIPOS_SUPORTADOS,
            tipo_vpn or "(vazio)",
        ),
    ]

    # Cada tecnologia declara o que precisa. Em VPN_MODE=host a lista vem vazia:
    # quem autentica é o cliente de VPN do operador, não este processo.
    for requisito in requisitos_do_tipo(tipo_vpn, mode=modo_vpn):
        if isinstance(requisito, tuple):
            # Grupo "pelo menos um": fontes alternativas (ex.: config WireGuard
            # por conteúdo OU por caminho). Nunca imprimimos o valor — só qual
            # fonte satisfez, para não vazar segredo.
            presentes = [v for v in requisito if str(getattr(config, v, "") or "")]
            checks.append(
                _check(
                    requisito[0].lower(),
                    bool(presentes),
                    f"via {presentes[0]}" if presentes else f"defina {' ou '.join(requisito)}",
                )
            )
        else:
            valor = str(getattr(config, requisito, "") or "")
            sensivel = any(marca in requisito.upper() for marca in _SEGREDOS)
            checks.append(
                _check(
                    requisito.lower(),
                    bool(valor),
                    _presenca(valor) if sensivel else (valor or "(vazio)"),
                )
            )
    return checks


def _checks_protheus() -> list[dict[str, Any]]:
    perfil = config.resolve_protheus_perfil()
    resources = Path(config.PROTHEUS_RESOURCES_DIR)
    return [
        _check("protheus_url", bool(perfil["url"]), perfil["url"] or "(vazio)"),
        _check("protheus_username", bool(perfil["username"]), _presenca(perfil["username"])),
        _check("protheus_password", bool(perfil["password"]), _presenca(perfil["password"])),
        _check("protheus_programa", bool(perfil["programa"]), perfil["programa"] or "(vazio)"),
        _check("protheus_ambiente", bool(perfil["ambiente"]), perfil["ambiente"] or "(vazio)"),
        _check("resources_dir", resources.is_dir(), str(resources)),
        _check("playwright_import", _importa("playwright"), "ok" if _importa("playwright") else "ausente"),
    ]


def _importa(modulo: str) -> bool:
    try:
        __import__(modulo)
        return True
    except Exception:
        return False


def _checks_classificacao_nf(fluxo: str) -> list[dict[str, Any]]:
    """Checks do data-plane TES 002. Bloqueantes só para fluxo classificar_nf."""
    checks = [
        _check("httpx_import", _importa("httpx"), "ok" if _importa("httpx") else "ausente"),
        _check(
            "openpyxl_import",
            _importa("openpyxl"),
            "ok" if _importa("openpyxl") else "ausente",
        ),
        _check(
            "protheus_api_mode",
            True,
            config.PROTHEUS_API_MODE or "(vazio)",
        ),
        _check(
            "lynn_api_mode",
            True,
            config.LYNN_API_MODE or "(vazio)",
        ),
        _check("pdf_share_mode", True, config.PDF_SHARE_MODE or "(vazio)"),
        _check(
            "folder_root_agent_lynn",
            bool(
                (
                    getattr(config, "FOLDER_FILES_AGENT_LYNN", "") or getattr(config, "FOLDER_ROOT_AGENT_LYNN", "")
                    or config.CLASSIFICADOR_NF_ROOT
                    or ""
                ).strip()
            ),
            (
                getattr(config, "FOLDER_FILES_AGENT_LYNN", "") or getattr(config, "FOLDER_ROOT_AGENT_LYNN", "")
                or config.CLASSIFICADOR_NF_ROOT
                or "(vazio)"
            ),
        ),
    ]

    if (config.PROTHEUS_API_MODE or "").strip().lower() == "http":
        checks.append(
            _check(
                "protheus_api_base_url",
                bool(config.PROTHEUS_API_BASE_URL),
                config.PROTHEUS_API_BASE_URL or "(vazio)",
            )
        )
        checks.append(
            _check(
                "protheus_api_token",
                bool(config.PROTHEUS_API_TOKEN),
                _presenca(config.PROTHEUS_API_TOKEN),
            )
        )

    if (config.LYNN_API_MODE or "").strip().lower() == "http":
        base = (config.LYNN_BASE_URL or config.LYNN_API_BASE_URL or "").strip()
        token = (config.LYNN_API_TOKEN or config.LYNN_API_KEY or "").strip()
        run_mode = (config.LYNN_RUN_MODE or "workflow").strip().lower()
        checks.append(
            _check(
                "lynn_api_base_url",
                bool(base),
                base or "(vazio)",
            )
        )
        checks.append(
            _check(
                "lynn_run_mode",
                run_mode in ("workflow", "flow", "flows", "agent", "agents"),
                config.LYNN_RUN_MODE or "(vazio)",
            )
        )
        checks.append(
            _check(
                "lynn_project",
                bool(config.LYNN_PROJECT),
                config.LYNN_PROJECT or "(vazio)",
            )
        )
        if run_mode in ("workflow", "flow", "flows"):
            checks.append(
                _check(
                    "lynn_workflow_id",
                    bool(config.LYNN_WORKFLOW_ID),
                    config.LYNN_WORKFLOW_ID or "(vazio)",
                )
            )
            checks.append(
                _check(
                    "lynn_agent_id",
                    True,
                    config.LYNN_AGENT_ID or "(opcional/agent depois)",
                )
            )
        else:
            checks.append(
                _check(
                    "lynn_agent_id",
                    bool(config.LYNN_AGENT_ID),
                    config.LYNN_AGENT_ID or "(vazio)",
                )
            )
            checks.append(
                _check(
                    "lynn_workflow_id",
                    True,
                    config.LYNN_WORKFLOW_ID or "(opcional/homolog)",
                )
            )
        checks.append(
            _check(
                "lynn_api_token",
                bool(token),
                _presenca(token),
            )
        )

    if (config.PDF_SHARE_MODE or "").strip().lower() == "local":
        casa = (
            getattr(config, "FOLDER_FILES_AGENT_LYNN", "") or getattr(config, "FOLDER_ROOT_AGENT_LYNN", "")
            or config.CLASSIFICADOR_NF_ROOT
            or ""
        ).strip()
        casa_path = Path(casa) if casa else None
        if casa_path is not None and casa_path.exists():
            try:
                from agent.jobs.classificar_nf.caminhos import garantir_pastas

                garantir_pastas(casa_path)
            except OSError:
                pass
        root = Path(config.PDF_SHARE_ROOT) if config.PDF_SHARE_ROOT else None
        checks.append(
            _check(
                "pdf_share_root",
                bool(root and root.is_dir()),
                str(root) if root else "(vazio)",
            )
        )

    fonte_ti = (getattr(config, "PDF_SHARE_SOURCE", "") or "").strip()
    if fonte_ti:
        fonte_path = Path(fonte_ti)
        acessivel = False
        try:
            acessivel = fonte_path.is_dir()
        except OSError:
            acessivel = False
        # Informativo: UNC pode falhar antes da VPN; o stage valida de novo no data-plane.
        checks.append(
            _check(
                "pdf_share_source",
                True,
                f"{fonte_ti} ({'ok' if acessivel else 'configurado; validar apos VPN'})",
            )
        )
    else:
        checks.append(
            _check("pdf_share_source", True, "(opcional/vazio)")
        )

    for label, path_str in (
        ("depara_natureza_despesa", config.DEPARA_NATUREZA_DESPESA_PATH),
        ("depara_codigo_servico", config.DEPARA_CODIGO_SERVICO_PATH),
        ("depara_natureza_rendimento", config.DEPARA_NATUREZA_RENDIMENTO_PATH),
        ("depara_vencimento_especial", config.DEPARA_VENCIMENTO_ESPECIAL_PATH),
    ):
        if not path_str:
            # Informativo: F2 permite tabelas injetadas; F3 cobrará no fluxo real.
            checks.append(_check(label, True, "(opcional/vazio)"))
            continue
        path = Path(path_str)
        checks.append(_check(label, path.is_file(), str(path)))

    return checks


# Checks cujo fracasso impede a automação de UI.
_BLOQUEANTES_UI = {
    "protheus": ("protheus_url", "protheus_username", "protheus_password", "playwright_import"),
}

_BLOQUEANTES_DATA = (
    "httpx_import",
    "openpyxl_import",
)


def run_preflight(
    *,
    erp: str | None = None,
    runtime: str | None = None,
    fluxo: str = "",
) -> dict[str, Any]:
    """Valida configuração e alcance, sem tocar VPN, sessão remota ou UI."""
    tipo_erp = config.normalize_erp_type(erp)
    tipo_runtime = config.normalize_runtime_mode(runtime)
    fluxo_norm = (fluxo or "").strip().lower()

    checks = _checks_comuns(tipo_erp, tipo_runtime)
    if tipo_erp == "protheus":
        checks += _checks_protheus()
    else:
        checks.append(_check("erp_type", False, f"ERP não suportado neste fork: {tipo_erp}"))

    checks += _checks_classificacao_nf(fluxo_norm)

    por_nome = {c["check"]: c for c in checks}
    bloqueantes = list(_BLOQUEANTES_UI.get(tipo_erp, ()))

    ready_ui = all(por_nome[n]["ok"] for n in bloqueantes if n in por_nome)

    exige_data = fluxo_norm in ("classificar_nf", "classificacao_nf", "tes002")
    if exige_data:
        ready_data = all(por_nome[n]["ok"] for n in _BLOQUEANTES_DATA if n in por_nome)
        if (config.PROTHEUS_API_MODE or "").lower() == "http":
            ready_data = ready_data and por_nome.get("protheus_api_base_url", {}).get("ok", False)
        if (config.LYNN_API_MODE or "").lower() == "http":
            ready_data = ready_data and por_nome.get("lynn_api_base_url", {}).get("ok", False)
            ready_data = ready_data and por_nome.get("lynn_run_mode", {}).get("ok", False)
            ready_data = ready_data and por_nome.get("lynn_project", {}).get("ok", False)
            ready_data = ready_data and por_nome.get("lynn_api_token", {}).get("ok", False)
            run_mode = (config.LYNN_RUN_MODE or "workflow").strip().lower()
            if run_mode in ("workflow", "flow", "flows"):
                ready_data = ready_data and por_nome.get("lynn_workflow_id", {}).get(
                    "ok", False
                )
            else:
                ready_data = ready_data and por_nome.get("lynn_agent_id", {}).get(
                    "ok", False
                )
        if (config.PDF_SHARE_MODE or "").lower() == "local":
            ready_data = ready_data and por_nome.get("pdf_share_root", {}).get("ok", False)
    else:
        ready_data = True

    return {
        # `ok` diz que o preflight rodou; ready_ui é que decide seguir.
        "ok": True,
        "erp": tipo_erp,
        "runtime": tipo_runtime,
        "fluxo": fluxo or "",
        "ready_ui": ready_ui,
        "ready_data": ready_data,
        "ready_edi": True,
        "checks": checks,
        "cwd": os.getcwd(),
    }
