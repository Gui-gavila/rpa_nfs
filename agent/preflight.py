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


# Checks cujo fracasso impede a automação de UI.
_BLOQUEANTES_UI = {
    "protheus": ("protheus_url", "protheus_username", "protheus_password", "playwright_import"),
}


def run_preflight(
    *,
    erp: str | None = None,
    runtime: str | None = None,
    fluxo: str = "",
) -> dict[str, Any]:
    """Valida configuração e alcance, sem tocar VPN, sessão remota ou UI."""
    tipo_erp = config.normalize_erp_type(erp)
    tipo_runtime = config.normalize_runtime_mode(runtime)

    checks = _checks_comuns(tipo_erp, tipo_runtime)
    if tipo_erp == "protheus":
        checks += _checks_protheus()
    else:
        checks.append(_check("erp_type", False, f"ERP não suportado neste fork: {tipo_erp}"))

    por_nome = {c["check"]: c for c in checks}
    bloqueantes = list(_BLOQUEANTES_UI.get(tipo_erp, ()))

    ready_ui = all(por_nome[n]["ok"] for n in bloqueantes if n in por_nome)

    return {
        # `ok` diz que o preflight rodou; ready_ui é que decide seguir.
        "ok": True,
        "erp": tipo_erp,
        "runtime": tipo_runtime,
        "fluxo": fluxo or "",
        "ready_ui": ready_ui,
        "ready_edi": True,
        "checks": checks,
        "cwd": os.getcwd(),
    }
