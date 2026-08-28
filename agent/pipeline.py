"""Pipeline canônico do framework Carol App RPA.

Estágios partilhados, sempre nesta ordem:

    preflight → vpn → pre_hooks → sessao_remota → login_erp
              → run_agente → post_hooks → cleanup

O contrato de resultado é um envelope de dados, não exceções: cada estágio
registra um passo com `ok` e detalhe, e a falha vira um slug estável em `erro`.
Isso é o que permite ao worker reportar *qual passo* falhou numa execução
agendada sem ninguém olhando, e o que torna `--json` útil para observabilidade.

Registrar um agente novo = acrescentar uma entrada em AGENTES. O `erp` de cada
agente é validado contra o ERP_TYPE ativo, para que uma combinação inválida
falhe no preflight e não no meio da UI.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ESTAGIOS = (
    "preflight",
    "vpn",
    "pre_hooks",
    "sessao_remota",
    "login_erp",
    "run_agente",
    "post_hooks",
    "cleanup",
)

# Registro de agentes disponíveis: nome canônico → metadados.
#   erp      ERP exigido pelo agente (valida contra ERP_TYPE)
#   programa identificador do programa/rotina no ERP (livre; "" quando não aplica)
AGENTES: dict[str, dict[str, str]] = {
    # Protheus — smoke de conectividade: autentica e chega à tela principal.
    "login": {"erp": "protheus", "programa": ""},
    # Classificação NFS TES 002 — data-plane + UI MATA103 (UI completa em F4).
    "classificar_nf": {"erp": "protheus", "programa": "MATA103"},
}

_ALIASES: dict[str, str] = {
    "login": "login",
    "smoke": "login",
    "protheus": "login",
    "classificar_nf": "classificar_nf",
    "classificacao_nf": "classificar_nf",
    "tes002": "classificar_nf",
}


def normalize_agente(fluxo: str) -> str:
    """Normaliza alias de CLI para o nome canônico do agente."""
    key = (fluxo or "").strip().lower()
    if key not in _ALIASES:
        disponiveis = "|".join(sorted(AGENTES))
        raise ValueError(f"fluxo desconhecido: {fluxo!r}; use {disponiveis}")
    return _ALIASES[key]


def erp_do_agente(agente: str) -> str:
    """ERP exigido pelo agente informado."""
    return AGENTES[normalize_agente(agente)]["erp"]


def novo_resultado(agente: str) -> dict[str, Any]:
    """Contrato base de resultado do pipeline."""
    meta = AGENTES.get(agente, {})
    return {
        "ok": False,
        "agente": agente,
        "erp": meta.get("erp"),
        "programa": meta.get("programa") or None,
        "passos": [],
        "artefatos": {},
        "erro": None,
    }


def registrar_passo(
    result: dict[str, Any],
    nome: str,
    *,
    ok: bool,
    detalhe: str = "",
) -> None:
    """Acrescenta um estágio executado ao resultado e grava no log operacional."""
    result.setdefault("passos", []).append(
        {"passo": nome, "ok": ok, "detalhe": detalhe}
    )
    marca = "OK" if ok else "FALHA"
    extra = f" {detalhe}" if detalhe else ""
    logger.info("[pipeline] passo=%s %s%s", nome, marca, extra)


# Chaves que, quando devolvidas por um agente, também são publicadas em
# `artefatos` — é o que o operador procura primeiro ao auditar uma corrida.
_CHAVES_ARTEFATO = (
    "nomeArquivo",
    "caminhoArquivo",
    "caminho_relatorio",
    "caminho_checkpoint",
    "screenshots",
    "anexos_email",
    "params",
    "modulo",
)


def fundir_resultado_agente(
    pipeline: dict[str, Any],
    agente_result: dict[str, Any],
) -> dict[str, Any]:
    """Mescla a saída do ErpAgent no envelope do pipeline.

    Chaves desconhecidas são preservadas na raiz: uma especialização pode
    devolver o que precisar sem alterar este módulo.
    """
    out = dict(pipeline)
    out["ok"] = bool(agente_result.get("ok"))
    if agente_result.get("erro"):
        out["erro"] = agente_result["erro"]

    artefatos = dict(out.get("artefatos") or {})
    for chave, valor in agente_result.items():
        if chave in ("ok", "erro"):
            continue
        out[chave] = valor
        if chave in _CHAVES_ARTEFATO:
            artefatos[chave] = valor
    out["artefatos"] = artefatos
    return out
