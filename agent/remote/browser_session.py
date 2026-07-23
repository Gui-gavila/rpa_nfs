"""Sessão de UI via browser (Protheus SmartClient Web).

Tratar o browser como `RemoteSession` mantém o pipeline
(preflight → vpn → sessão → login → run) estável: abrir a sessão, esperar
ficar utilizável, encerrar no fim.

Playwright **síncrono**, alinhado às demais camadas.

O viewport é fixo e isso é requisito, não preferência: o SmartClient Web
desenha em canvas, a automação usa coordenadas calibradas, e um viewport
variável as invalida.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.remote.base import RemoteSession

logger = logging.getLogger(__name__)


class BrowserSession(RemoteSession):
    """Chromium + navegação até a URL do ERP web."""

    def __init__(
        self,
        *,
        url: str,
        width: int = 1280,
        height: int = 720,
        headless: bool = True,
        slow_mo_ms: int = 0,
        locale: str = "pt-BR",
        web_agent_bin: str = "",
        web_agent_port: int = 0,
        web_agent_forward_host: str = "",
        web_agent_forward_port: int = 0,
        load_timeout_s: float = 40.0,
    ) -> None:
        self.url = (url or "").strip()
        self.width = int(width)
        self.height = int(height)
        self.headless = bool(headless)
        self.slow_mo_ms = int(slow_mo_ms)
        self.locale = locale
        # Vazios = Web Agent gerido pelo SO (caso típico do Windows).
        self.web_agent_bin = web_agent_bin
        self.web_agent_port = int(web_agent_port or 0)
        self.web_agent_forward_host = (web_agent_forward_host or "").strip()
        self.web_agent_forward_port = int(web_agent_forward_port or 0)
        self.load_timeout_s = float(load_timeout_s)

        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self.page: Any = None

    # --- ciclo de vida ------------------------------------------------------

    def connect(self) -> bool:
        if self.is_ready():
            logger.info("[BrowserSession] sessão já ativa")
            return True
        if not self.url:
            logger.error("[BrowserSession] URL do ERP não configurada (PROTHEUS_URL)")
            return False

        if self.web_agent_bin and self.web_agent_port:
            from agent.remote.web_agent import garantir_web_agent

            if not garantir_web_agent(
                binario=self.web_agent_bin,
                porta=self.web_agent_port,
                forward_host=self.web_agent_forward_host,
                forward_port=self.web_agent_forward_port,
            ):
                logger.error("[BrowserSession] Web Agent indisponível — abortando")
                return False

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error(
                "[BrowserSession] Playwright não instalado (pip install playwright "
                "&& playwright install chromium)"
            )
            return False

        args: list[str] = []
        if self.headless:
            # Obrigatórios em container: sem /dev/shm generoso e sem user namespaces.
            args += ["--no-sandbox", "--disable-dev-shm-usage"]
        # Web Agent / shim TLS usa certificado TOTVS (WSS em 127.0.0.1).
        args += ["--ignore-certificate-errors", "--allow-insecure-localhost"]

        logger.info(
            "[BrowserSession] abrindo Chromium headless=%s viewport=%sx%s",
            self.headless, self.width, self.height,
        )
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self.headless, args=args, slow_mo=self.slow_mo_ms
            )
            self._context = self._browser.new_context(
                viewport={"width": self.width, "height": self.height},
                ignore_https_errors=True,
                locale=self.locale,
            )
            self.page = self._context.new_page()
            logger.info("[BrowserSession] navegando para %s", self.url)
            self.page.goto(self.url, timeout=self.load_timeout_s * 1000)
            self.page.wait_for_load_state("load")
        except Exception as e:
            logger.error("[BrowserSession] falha ao abrir a sessão: %s", e, exc_info=True)
            self.disconnect()
            return False

        logger.info("[BrowserSession] sessão pronta")
        return True

    def disconnect(self) -> None:
        """Fecha na ordem inversa da abertura, tolerando estado parcial."""
        for rotulo, alvo, metodo in (
            ("context", self._context, "close"),
            ("browser", self._browser, "close"),
            ("playwright", self._playwright, "stop"),
        ):
            if alvo is None:
                continue
            try:
                getattr(alvo, metodo)()
            except Exception as e:
                logger.debug("[BrowserSession] erro ao fechar %s: %s", rotulo, e)
        self._context = self._browser = self._playwright = None
        self.page = None
        logger.info("[BrowserSession] sessão encerrada")

    def is_ready(self) -> bool:
        if self.page is None:
            return False
        try:
            return not self.page.is_closed()
        except Exception:
            return False

    # --- acesso à superfície ------------------------------------------------

    def surface(self, *, resources_dir: str = "resources") -> Any:
        """PlaywrightSurface ligada a esta sessão. Exige `connect()` antes."""
        if self.page is None:
            raise RuntimeError("BrowserSession.connect() deve ser chamado antes de surface()")
        from agent.surface.browser import PlaywrightSurface

        return PlaywrightSurface(self.page, resources_dir=resources_dir)
