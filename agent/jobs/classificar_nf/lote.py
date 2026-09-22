"""Agrupamento auxiliar por filial. A sessão UI entra só na holding 0101."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from agent.jobs.classificar_nf.checkpoint import ItemCheckpoint


def agrupar_por_filial(itens: list[ItemCheckpoint]) -> list[list[ItemCheckpoint]]:
    """Agrupa pela filial, na ordem em que cada código aparece na fila."""
    grupos: list[list[ItemCheckpoint]] = []
    indice: dict[str, int] = {}
    for item in itens:
        fil = (item.filial_codigo or "").strip()
        if fil not in indice:
            indice[fil] = len(grupos)
            grupos.append([])
        grupos[indice[fil]].append(item)
    return grupos


def deve_enviar_email_fiscal(
    *,
    frequencia: str,
    elegiveis_restantes: int,
    pronto_ui: int,
) -> bool:
    """ciclo = todo worker; esgotado = só quando não resta LYNN nem fila UI."""
    freq = (frequencia or "ciclo").strip().lower()
    if freq in ("esgotado", "final", "fim"):
        return int(elegiveis_restantes or 0) <= 0 and int(pronto_ui or 0) <= 0
    return True


def deve_repetir_ciclo(
    *,
    ciclo_atual: int,
    ciclos_max: int,
    elegiveis_restantes: int,
    pronto_ui: int,
) -> bool:
    """Mais um bloco no mesmo processo só se o teto CICLOS ainda cabe e há trabalho."""
    teto = max(1, int(ciclos_max or 1))
    if int(ciclo_atual or 0) >= teto:
        return False
    return int(elegiveis_restantes or 0) > 0 or int(pronto_ui or 0) > 0


def sla_operacional(referencia: date) -> dict[str, Any]:
    """Janela F7: fase 1 até dia 15 (níveis 1–3); fase 2 até dia 25 (restante)."""
    dia = int(referencia.day)
    if dia <= 15:
        return {
            "fase": 1,
            "prazo_dia": 15,
            "nivel_max_sugerido": 3,
            "janela": "ate_dia_15",
        }
    if dia <= 25:
        return {
            "fase": 2,
            "prazo_dia": 25,
            "nivel_max_sugerido": 0,
            "janela": "ate_dia_25",
        }
    return {
        "fase": 2,
        "prazo_dia": 25,
        "nivel_max_sugerido": 0,
        "janela": "apos_dia_25",
    }


def montar_observabilidade(
    *,
    duracao_s: float,
    ciclos_executados: int = 1,
    elegiveis_restantes: int = 0,
    pronto_ui: int = 0,
    classificadas: int = 0,
    falhas_ui: int = 0,
    nivel_max: int = 0,
    referencia: date | None = None,
) -> dict[str, Any]:
    """Métricas de lote para --json / resumo da corrida (SLA monitorável)."""
    restantes = int(elegiveis_restantes or 0)
    pronto = int(pronto_ui or 0)
    return {
        "duracao_s": round(float(duracao_s or 0), 3),
        "ciclos_executados": max(1, int(ciclos_executados or 1)),
        "elegiveis_restantes": restantes,
        "pronto_ui": pronto,
        "fila_residual": restantes + pronto,
        "classificadas": int(classificadas or 0),
        "falhas_ui": int(falhas_ui or 0),
        "nivel_max": int(nivel_max or 0),
        "sla": sla_operacional(referencia or date.today()),
    }


def montar_resumo_sessao(
    *,
    n_pendentes_protheus: int = 0,
    n_sessao: int = 0,
    n_pdfs_lynn: int = 0,
    n_pronto_ui: int = 0,
    n_classificadas: int = 0,
    n_erros: int = 0,
    inicio: datetime | None = None,
    fim: datetime | None = None,
    duracao_s: float = 0.0,
) -> dict[str, Any]:
    """Números da sessão de classificação para o log operacional de fecho."""
    n_lynn = int(n_pdfs_lynn or 0)
    duracao = round(float(duracao_s or 0), 3)
    media = round(duracao / n_lynn, 3) if n_lynn else None
    return {
        "n_pendentes_protheus": int(n_pendentes_protheus or 0),
        "n_sessao": int(n_sessao or 0),
        "n_pdfs_lynn": n_lynn,
        "n_arquivos_lynn": n_lynn,
        "n_pronto_ui": int(n_pronto_ui or 0),
        "n_classificadas": int(n_classificadas or 0),
        "n_erros": int(n_erros or 0),
        "inicio": inicio.strftime("%Y-%m-%d %H:%M:%S") if inicio else "",
        "fim": fim.strftime("%Y-%m-%d %H:%M:%S") if fim else "",
        "duracao_s": duracao,
        "tempo_medio_s": media,
    }


def formatar_resumo_sessao(resumo: dict[str, Any]) -> list[str]:
    """Linhas pt-BR do bloco de fecho (sem prefixo de logger)."""
    media = resumo.get("tempo_medio_s")
    media_txt = "n/a" if media is None else f"{media:.3f}s"
    return [
        "--- resumo da sessão ---",
        f"pendentes no Protheus: {resumo.get('n_pendentes_protheus', 0)}",
        f"notas da sessão: {resumo.get('n_sessao', 0)}",
        f"arquivos enviados ao LYNN: {resumo.get('n_arquivos_lynn', 0)}",
        f"processadas no LYNN: {resumo.get('n_pdfs_lynn', 0)}",
        f"a classificar no Protheus: {resumo.get('n_pronto_ui', 0)}",
        f"classificadas no Protheus: {resumo.get('n_classificadas', 0)}",
        f"notas com erro: {resumo.get('n_erros', 0)}",
        f"inicio: {resumo.get('inicio') or '-'}",
        f"fim: {resumo.get('fim') or '-'}",
        f"tempo total: {resumo.get('duracao_s', 0)}s",
        f"tempo médio por PDF LYNN: {media_txt}",
    ]
