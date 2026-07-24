"""Sessão de UI via browser (Protheus SmartClient Web).

Tratar o browser como `RemoteSession` mantém o pipeline
(preflight → vpn → sessão → login → run) estável: abrir a sessão, esperar
ficar utilizável, encerrar no fim.

Playwright **síncrono**, alinhado às demais camadas.

Resolução invariante (headed = headless)
----------------------------------------
O SmartClient Web desenha em canvas; clique por imagem e coordenadas
calibradas exigem o mesmo frame em qualquer modo. Por isso:

- viewport lógico fixo (`BROWSER_WIDTH`×`BROWSER_HEIGHT`);
- `device_scale_factor=1` (ignora DPI do Windows / monitor);
- após maximizar a janela OS (só headed), o viewport é reafirmado.

Maximizar a janela não muda o tamanho do frame capturado.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.remote.base import RemoteSession

logger = logging.getLogger(__name__)

# Escala física do frame. 1.0 = 1 pixel de screenshot por CSS px.
# Sem isto, headed no Windows (125%/150%) diverge do headless e quebra CV.
DEVICE_SCALE_FACTOR = 1.0


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

    def _args_chromium(self) -> list[str]:
        """Flags comuns headed/headless — resolução estável para visão."""
        args = [
            # Força DPR=1 mesmo com scaling do SO (lab Windows).
            f"--force-device-scale-factor={DEVICE_SCALE_FACTOR:g}",
            "--ignore-certificate-errors",
            "--allow-insecure-localhost",
        ]
        if self.headless:
            # Obrigatórios em container: sem /dev/shm generoso e sem user namespaces.
            args += ["--no-sandbox", "--disable-dev-shm-usage"]
        else:
            # Janela OS maximizada; o viewport Playwright continua fixo abaixo.
            args += ["--start-maximized"]
        return args

    def _opcoes_contexto(self) -> dict[str, Any]:
        """Contexto idêntico em headed e headless (viewport + escala)."""
        return {
            "viewport": {"width": self.width, "height": self.height},
            "device_scale_factor": DEVICE_SCALE_FACTOR,
            "ignore_https_errors": True,
            "locale": self.locale,
        }

    def _maximizar_janela(self) -> None:
        """Maximiza a janela do Chromium (headed). Não altera o viewport lógico."""
        if self.headless or self.page is None or self._context is None:
            return
        try:
            cdp = self._context.new_cdp_session(self.page)
            janela = cdp.send("Browser.getWindowForTarget")
            cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": janela["windowId"],
                    "bounds": {"windowState": "maximized"},
                },
            )
            logger.info(
                "[BrowserSession] janela maximizada (viewport lógico %sx%s)",
                self.width, self.height,
            )
        except Exception as e:
            logger.warning("[BrowserSession] não foi possível maximizar a janela: %s", e)

    def _garantir_resolucao(self) -> None:
        """Reafirma viewport após launch/maximize e valida DPR efetivo.

        Garante que headed e headless produzam o mesmo frame para clique por imagem.
        """
        if self.page is None:
            return
        try:
            self.page.set_viewport_size({"width": self.width, "height": self.height})
        except Exception as e:
            logger.warning("[BrowserSession] set_viewport_size falhou: %s", e)
            return

        vp = getattr(self.page, "viewport_size", None) or {}
        vw = int(vp.get("width") or 0)
        vh = int(vp.get("height") or 0)
        try:
            dpr = float(self.page.evaluate("window.devicePixelRatio") or 0.0)
        except Exception as e:
            logger.warning("[BrowserSession] devicePixelRatio indisponível: %s", e)
            dpr = 0.0

        logger.info(
            "[BrowserSession] resolução efetiva viewport=%sx%s dpr=%s (alvo %sx%s dpr=%s)",
            vw, vh, dpr, self.width, self.height, DEVICE_SCALE_FACTOR,
        )
        if vw and vh and (vw != self.width or vh != self.height):
            logger.error(
                "[BrowserSession] viewport divergente do configurado — "
                "clique por imagem pode falhar"
            )
        if dpr and abs(dpr - DEVICE_SCALE_FACTOR) > 0.01:
            logger.error(
                "[BrowserSession] devicePixelRatio=%s (esperado %s) — "
                "headed/headless vão divergir no matching",
                dpr, DEVICE_SCALE_FACTOR,
            )

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

        args = self._args_chromium()
        logger.info(
            "[BrowserSession] abrindo Chromium headless=%s viewport=%sx%s scale=%s",
            self.headless, self.width, self.height, DEVICE_SCALE_FACTOR,
        )
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=self.headless, args=args, slow_mo=self.slow_mo_ms
            )
            self._context = self._browser.new_context(**self._opcoes_contexto())
            self.page = self._context.new_page()
            self._maximizar_janela()
            # Maximize pode interferir no layout da janela; trava de novo o viewport.
            self._garantir_resolucao()
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
