"""Logging em ficheiro para corridas agendadas (ponte T2 / Agendador / cron).

Um agente RPA roda sem ninguém olhando. O log diário em ficheiro é a única
evidência do que aconteceu. Cinco linhas em branco separam corridas no
mesmo ficheiro diário; o worker grava o envelope de sessão (início/fim).

Padrão (paridade CNAB `bot-carol-t03071-cnab-pagto`): `logging` stdlib,
`FileHandler` na root, um ficheiro por dia, append se houver várias corridas.
Destino operacional: `{FOLDER_FILES_AGENT_LYNN}/04_Logs/{ANOMES}/<erp>-YYYYMMDD.log`.

Convencao futura: todo módulo operacional usa `logging.getLogger(__name__)` e
regista INFO das acoes (nunca `print`, nunca segredos). O handler na root
captura automaticamente loggers novos.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

_CONFIGURED = False
_SEPARATOR_WRITTEN = False
_LOG_PATH: Path | None = None

_LOGGERS_RUIDOSOS = (
    "httpcore",
    "httpcore.http11",
    "httpcore.connection",
    "httpcore.proxy",
    "playwright",
    "urllib3",
)


def resolve_log_dir(explicit: str | Path | None = None) -> Path:
    """Pasta de logs: arg > LOG_DIR > 04_Logs/ANOMES > fallbacks CNAB > ./logs."""
    if explicit:
        return Path(explicit)
    env = (os.getenv("LOG_DIR") or "").strip()
    if env:
        return Path(env)
    pasta = _pasta_logs_classificador()
    if pasta is not None:
        return pasta
    home = (os.getenv("AGENT_RPA_HOME") or "").strip()
    if home:
        return Path(home) / "logs"
    agent_rpa = Path(r"C:\AgentRPA")
    if agent_rpa.is_dir():
        return agent_rpa / "logs"
    return Path("logs")


def _pasta_logs_classificador() -> Path | None:
    """`{FOLDER_FILES_AGENT_LYNN}/04_Logs/{YYYYMM}` quando a casa do agente existe."""
    try:
        from agent.jobs.classificar_nf.caminhos import garantir_pastas
        from agent import config

        root = (
            getattr(config, "FOLDER_FILES_AGENT_LYNN", "")
            or getattr(config, "FOLDER_ROOT_AGENT_LYNN", "")
            or getattr(config, "CLASSIFICADOR_NF_ROOT", "")
            or ""
        ).strip()
        if not root:
            return None
        base = Path(root)
        env_root = (
            os.getenv("FOLDER_FILES_AGENT_LYNN")
            or os.getenv("FOLDER_ROOT_AGENT_LYNN")
            or ""
        ).strip()
        if not base.exists() and not env_root:
            return None
        return garantir_pastas(base)["logs_anomes"]
    except Exception:
        return None


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


def daily_log_filename(prefix: str | None = None, *, when: datetime | None = None) -> str:
    """Nome canónico ``<erp>-YYYYMMDD.log`` (Architecture §12)."""
    dia = (when or datetime.now()).strftime("%Y%m%d")
    return f"{resolve_log_prefix(prefix)}-{dia}.log"


def get_log_path() -> Path | None:
    """Ficheiro de log da corrida atual, se já configurado."""
    return _LOG_PATH


def escrever_separador_corrida(log_path: Path) -> None:
    """Cinco linhas em branco antes do primeiro log da corrida (mesmo ficheiro diário)."""
    with log_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n\n\n\n\n")


def _append_run_separator(log_path: Path) -> None:
    escrever_separador_corrida(log_path)


def setup_run_logging(
    *,
    log_dir: str | Path | None = None,
    level: str | int | None = None,
    prefix: str | None = None,
) -> Path:
    """Configura consola + ficheiro diário ``<prefix>-YYYYMMDD.log``.

    Idempotente: chamar de novo no mesmo processo não duplica handlers nem
    reescreve o separador. Devolve o path do ficheiro do dia.

    O ficheiro operacional fica em INFO (legível em 04_Logs). A consola segue
    `LOG_LEVEL` (DEBUG no lab).
    """
    global _CONFIGURED, _SEPARATOR_WRITTEN, _LOG_PATH

    if isinstance(level, int):
        lvl = level
    else:
        lvl = getattr(logging, str(level or os.getenv("LOG_LEVEL") or "INFO").upper(), logging.INFO)

    file_level_name = (os.getenv("LOG_FILE_LEVEL") or "INFO").strip().upper()
    file_level = getattr(logging, file_level_name, logging.INFO)

    out_dir = resolve_log_dir(log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / daily_log_filename(prefix)
    _LOG_PATH = log_path

    # Separador direto no ficheiro, sem passar pelo Formatter (não queremos
    # timestamp de logging no banner). Uma vez por processo.
    if not _SEPARATOR_WRITTEN:
        _append_run_separator(log_path)
        _SEPARATOR_WRITTEN = True

    if not _CONFIGURED:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        root = logging.getLogger()
        root.setLevel(min(lvl, file_level))

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
        file_handler.setLevel(file_level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
        _CONFIGURED = True

        for nome in _LOGGERS_RUIDOSOS:
            logging.getLogger(nome).setLevel(logging.WARNING)

    logging.getLogger("agent").setLevel(min(lvl, file_level))
    return log_path
