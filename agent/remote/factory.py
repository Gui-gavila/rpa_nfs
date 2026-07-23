"""Fábrica de sessões remotas — browser (Protheus SmartClient Web).

O tipo de sessão normalmente é derivado de ERP_TYPE + RUNTIME_MODE
(ver `agent.config.resolve_session_type`); passar `session_type` explícito
sobrepõe essa derivação.
"""

from __future__ import annotations

import logging
import sys

from agent import config
from agent.remote.base import RemoteSession

logger = logging.getLogger(__name__)


def _sessao_browser() -> RemoteSession:
    from agent.remote.browser_session import BrowserSession

    # No Windows o Web Agent é instalado e gerido pelo SO; só o container
    # precisa subi-lo (Electron em modo tray sobre Xvfb) ou encaminhar ao host
    # (lab Docker Desktop com WEB_AGENT_FORWARD_HOST).
    gerir_web_agent = sys.platform != "win32"
    return BrowserSession(
        url=config.PROTHEUS_URL,
        width=config.BROWSER_WIDTH,
        height=config.BROWSER_HEIGHT,
        headless=config.BROWSER_HEADLESS,
        slow_mo_ms=config.BROWSER_SLOW_MO_MS,
        locale=config.BROWSER_LOCALE,
        web_agent_bin=config.WEB_AGENT_BIN if gerir_web_agent else "",
        web_agent_port=config.WEB_AGENT_PORT if gerir_web_agent else 0,
        web_agent_forward_host=config.WEB_AGENT_FORWARD_HOST if gerir_web_agent else "",
        web_agent_forward_port=config.WEB_AGENT_FORWARD_PORT if gerir_web_agent else 0,
        load_timeout_s=config.PROTHEUS_UI_LOAD_TIMEOUT_S,
    )


def get_remote_session(
    *,
    session_type: str | None = None,
    erp: str | None = None,
    runtime: str | None = None,
    surface=None,
    drive_mounts: list[tuple[str, str]] | None = None,
) -> RemoteSession:
    """Devolve a RemoteSession adequada (neste fork: apenas browser)."""
    tipo = config.resolve_session_type(erp=erp, runtime=runtime, session=session_type)
    logger.info("[Remote Factory] SESSION_TYPE=%s", tipo)

    if tipo == "browser":
        return _sessao_browser()

    raise ValueError(
        f"SESSION_TYPE não suportado neste fork: {tipo!r}. Use browser (Protheus)."
    )
