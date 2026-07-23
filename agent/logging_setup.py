"""Logging em ficheiro para corridas agendadas (ponte T2 / Agendador / cron).

Um agente RPA roda sem ninguém olhando. O log diário em ficheiro é a única
evidência do que aconteceu, e o separador de início é o que permite distinguir
corridas sucessivas dentro do mesmo ficheiro.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

_CONFIGURED = False
_SEPARATOR_WRITTEN = False
_LOG_PATH: Path | None = None


def resolve_log_dir(explicit: str | Path | None = None) -> Path:
    """Pasta de logs: arg > LOG_DIR > AGENT_RPA_HOME/logs > C:\\AgentRPA\\logs > ./logs."""
    if explicit:
        return Path(explicit)
    env = (os.getenv("LOG_DIR") or "").strip()
    if env:
        return Path(env)
    home = (os.getenv("AGENT_RPA_HOME") or "").strip()
    if home:
        return Path(home) / "logs"
    agent_rpa = Path(r"C:\AgentRPA")
    if agent_rpa.is_dir():
        return agent_rpa / "logs"
    return Path("logs")


def resolve_log_prefix(explicit: str | None = None) -> str:
    """Prefixo do ficheiro diário: arg > LOG_PREFIX > ERP_TYPE ativo > 'agent'.

    O ERP vem de `agent.config` (import tardio) e não de `os.getenv`, para que o
    default do config valha aqui também. O import é adiado de propósito: este
    módulo precisa continuar utilizável sem `.env`, antes de qualquer config.
    """
    for candidato in (explicit, os.getenv("LOG_PREFIX")):
        if (candidato or "").strip():
            return str(candidato).strip().lower()
    try:
        from agent.config import normalize_erp_type

        return normalize_erp_type()
    except Exception:
        return "agent"


def get_log_path() -> Path | None:
    """Ficheiro de log da corrida atual, se já configurado."""
    return _LOG_PATH


def _append_run_separator(log_path: Path) -> None:
    """Marcador de início — separa corridas dentro do ficheiro diário."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = ["", "", "", "", "", f"========== INICIO DA EXECUCAO {stamp} pid={os.getpid()} ==========", ""]
    with log_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def setup_run_logging(
    *,
    log_dir: str | Path | None = None,
    level: str | int | None = None,
    prefix: str | None = None,
) -> Path:
    """Configura consola + ficheiro diário ``<prefix>-YYYYMMDD.log``.

    Idempotente: chamar de novo no mesmo processo não duplica handlers nem
    reescreve o separador. Devolve o path do ficheiro do dia.
    """
    global _CONFIGURED, _SEPARATOR_WRITTEN, _LOG_PATH

    if isinstance(level, int):
        lvl = level
    else:
        lvl = getattr(logging, str(level or os.getenv("LOG_LEVEL") or "INFO").upper(), logging.INFO)

    out_dir = resolve_log_dir(log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    log_path = out_dir / f"{resolve_log_prefix(prefix)}-{day}.log"
    _LOG_PATH = log_path

    # Separador direto no ficheiro, sem passar pelo Formatter (não queremos
    # timestamp de logging no banner). Uma vez por processo.
    if not _SEPARATOR_WRITTEN:
        _append_run_separator(log_path)
        _SEPARATOR_WRITTEN = True

    if not _CONFIGURED:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        root = logging.getLogger()
        root.setLevel(lvl)

        has_stream = any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
            for h in root.handlers
        )
        if not has_stream:
            sh = logging.StreamHandler()
            sh.setLevel(lvl)
            sh.setFormatter(fmt)
            root.addHandler(sh)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(lvl)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
        _CONFIGURED = True

    logging.getLogger("agent").setLevel(lvl)
    logging.getLogger("agent").info(
        "[logging] INICIO DA EXECUCAO ficheiro=%s level=%s pid=%s",
        log_path,
        logging.getLevelName(lvl),
        os.getpid(),
    )
    return log_path
