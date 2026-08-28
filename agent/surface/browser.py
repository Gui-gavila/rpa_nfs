"""Surface sobre uma página Playwright (Protheus SmartClient Web).

Playwright **síncrono**, deliberadamente. As camadas Surface/RemoteSession/
ErpAgent são síncronas; o stack deste projeto já operava o Protheus com
Playwright síncrono.

O SmartClient Web renderiza em canvas via protocolo binário: o DOM não expõe
inputs nem botões após a autenticação. Por isso a automação é por pixel e
teclado.

Escape hatch de DOM
-------------------
Telas HTML do SmartClient (login PO UI, e em alguns ambientes a de
programa/ambiente) expõem inputs reais — muitas vezes dentro de um *iframe*,
não na página `/webapp/` raiz. `fill_dom`/`click_dom`/`contar_dom` existem para
elas e **não fazem parte do contrato `Surface`**: são capacidades exclusivas
de browser. Um agente que as use está declaradamente acoplado a este backend.
"""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np

from agent.surface.base import Surface
from agent.surface.vision_mixin import VisionMixin

logger = logging.getLogger(__name__)

# Nomes de tecla do contrato (minúsculos) → nomes do Playwright.
_TECLAS = {
    "enter": "Enter", "return": "Enter",
    "tab": "Tab",
    "esc": "Escape", "escape": "Escape",
    "space": "Space", "spacebar": "Space",
    "delete": "Delete", "del": "Delete",
    "backspace": "Backspace",
    "home": "Home", "end": "End",
    "pageup": "PageUp", "pagedown": "PageDown",
    "up": "ArrowUp", "down": "ArrowDown",
    "left": "ArrowLeft", "right": "ArrowRight",
    "insert": "Insert",
    "ctrl": "Control", "control": "Control",
    "alt": "Alt", "shift": "Shift",
    "win": "Meta", "windows": "Meta", "cmd": "Meta", "meta": "Meta",
}


def _traduzir_tecla(tecla: str) -> str:
    """Converte 'ctrl+a' / 'enter' / 'f5' para a notação do Playwright."""
    partes = [p.strip() for p in (tecla or "").split("+") if p.strip()]
    traduzidas = []
    for parte in partes:
        low = parte.lower()
        if low in _TECLAS:
            traduzidas.append(_TECLAS[low])
        elif len(low) >= 2 and low[0] == "f" and low[1:].isdigit():
            traduzidas.append("F" + low[1:])  # Playwright exige F maiúsculo
        else:
            traduzidas.append(parte)
    return "+".join(traduzidas)


class PlaywrightSurface(VisionMixin, Surface):
    """Superfície de automação sobre uma `playwright.sync_api.Page`."""

    def __init__(self, page: Any, *, resources_dir: str = "resources") -> None:
        self.page = page
        self.resources_dir = resources_dir
        self._frame_scale: float | None = None
        self._rota = ""
        self._registrar_listeners()
        logger.info("[PlaywrightSurface] Inicializada")

    def _registrar_listeners(self) -> None:
        """Rastreia rota interna e erros. Falha em silêncio com dublês de teste."""

        def ao_navegar(frame: Any) -> None:
            self._rota = getattr(frame, "url", "") or ""
            logger.debug("[PlaywrightSurface] rota: %s", self._rota)

        def ao_console(msg: Any) -> None:
            # O canvas emite muito aviso de fonte/OTS — só erro interessa.
            if getattr(msg, "type", "") == "error":
                logger.warning("[PlaywrightSurface] console error: %s", getattr(msg, "text", ""))

        def ao_responder(resposta: Any) -> None:
            if getattr(resposta, "status", 0) >= 400:
                logger.warning(
                    "[PlaywrightSurface] HTTP %s: %s",
                    resposta.status, getattr(resposta, "url", ""),
                )

        try:
            self.page.on("framenavigated", ao_navegar)
            self.page.on("console", ao_console)
            self.page.on("response", ao_responder)
        except Exception as e:
            logger.debug("[PlaywrightSurface] listeners indisponíveis: %s", e)

    @property
    def frame_scale(self) -> float:
        """devicePixelRatio: o screenshot vem em pixels físicos, o clique em CSS.

        Consultado uma vez e memorizado — não muda durante a sessão e a chamada
        atravessa a ponte CDP, que não é barata dentro de um laço de polling.
        """
        if self._frame_scale is None:
            try:
                self._frame_scale = float(self.page.evaluate("window.devicePixelRatio") or 1.0)
            except Exception as e:
                logger.warning("[PlaywrightSurface] devicePixelRatio indisponível (%s); usando 1.0", e)
                self._frame_scale = 1.0
            logger.info("[PlaywrightSurface] frame_scale=%s", self._frame_scale)
        return self._frame_scale

    # --- contrato Surface ---------------------------------------------------

    def capture(self) -> np.ndarray | None:
        """Frame BGR do viewport (não full_page: coordenadas devem ser de viewport)."""
        try:
            dados = self.page.screenshot(full_page=False)
        except Exception as e:
            logger.warning("[PlaywrightSurface] falha ao capturar: %s", e)
            return None
        return cv2.imdecode(np.frombuffer(dados, dtype=np.uint8), cv2.IMREAD_COLOR)

    def click(self, x: int, y: int, *, clicks: int = 1, button: str = "left") -> None:
        self.page.mouse.click(x, y, click_count=max(int(clicks), 1), button=button)

    def type_text(self, text: str, *, delay_ms: int = 0) -> None:
        if not text:
            return
        # O TWebEngine perde caracteres quando a digitação é instantânea;
        # um atraso mínimo entre teclas é requisito, não estética.
        self.page.keyboard.type(text, delay=max(delay_ms, 0))

    def press(self, key: str) -> None:
        self.page.keyboard.press(_traduzir_tecla(key))

    # --- extras de browser (fora do contrato Surface) -----------------------

    def _encontrar_locator(self, selector: str, *, indice: int = 0) -> Any | None:
        """Localiza `selector` na página ou em qualquer frame (SmartClient).

        Devolve o locator já em `.nth(indice)`, ou None se nenhum alvo tiver
        elementos suficientes. Dublês de teste sem `count()` / `frames` caem
        no locator da página (comportamento antigo).
        """
        frames = getattr(self.page, "frames", None)
        alvos: list[Any] = list(frames) if frames else [self.page]

        for alvo in alvos:
            try:
                loc = alvo.locator(selector)
            except Exception:
                continue
            try:
                n = loc.count()
            except Exception:
                return loc.nth(indice)
            if n > indice:
                return loc.nth(indice)
        return None

    def _locator_dom(self, selector: str, *, indice: int = 0, timeout_s: float = 30.0) -> Any:
        """Espera o seletor aparecer em algum frame; senão usa a página (erro Playwright)."""
        import time

        deadline = time.time() + max(timeout_s, 0.0)
        while True:
            encontrado = self._encontrar_locator(selector, indice=indice)
            if encontrado is not None:
                return encontrado
            if time.time() >= deadline:
                break
            self.sleep(0.25)
        return self.page.locator(selector).nth(indice)

    def contar_dom(self, selector: str) -> int:
        """Quantos elementos batem o seletor na página + frames. 0 se indisponível."""
        frames = getattr(self.page, "frames", None)
        alvos: list[Any] = list(frames) if frames else [self.page]
        total = 0
        for alvo in alvos:
            try:
                total += int(alvo.locator(selector).count())
            except Exception:
                continue
        return total

    def fill_dom(self, selector: str, valor: str, *, indice: int = 0) -> None:
        """Preenche um input real do DOM (página ou iframe do SmartClient)."""
        self._locator_dom(selector, indice=indice, timeout_s=5.0).fill(
            valor, timeout=5_000
        )

    def fill_dom_por_rotulo(self, rotulo: str, valor: str, *, timeout_ms: int = 4000) -> bool:
        """Preenche o campo PO/HTML cujo rótulo visível é `rotulo` (ex.: Filial)."""
        frames = list(getattr(self.page, "frames", None) or [])
        if self.page is not None and self.page not in frames:
            frames = [self.page, *frames]
        for alvo in frames:
            candidatos = []
            try:
                candidatos.append(alvo.get_by_label(rotulo, exact=False))
            except Exception:
                pass
            try:
                candidatos.append(
                    alvo.locator("po-field, .po-field, po-combo, .po-combo")
                    .filter(has_text=rotulo)
                    .locator("input")
                )
            except Exception:
                pass
            for loc in candidatos:
                try:
                    if loc.count() <= 0:
                        continue
                    campo = loc.first
                    campo.click(timeout=timeout_ms)
                    campo.fill(valor, timeout=timeout_ms)
                    campo.press("Tab")
                    logger.info(
                        "[PlaywrightSurface] fill_dom_por_rotulo rotulo=%s", rotulo
                    )
                    return True
                except Exception:
                    continue
        return False

    def click_dom(
        self, selector: str, *, indice: int = 0, force: bool = False
    ) -> None:
        """Clica num elemento real do DOM (página ou iframe do SmartClient)."""
        self._locator_dom(selector, indice=indice).click(force=force)

    @property
    def rota(self) -> str:
        """Rota interna do SPA, capturada dos eventos de navegação de frame.

        `page.url` não serve para o SmartClient Web: ele permanece em /webapp/
        enquanto a aplicação troca de tela internamente.
        """
        return self._rota

    def aguardar_rota(self, trecho: str, timeout_s: float = 40.0) -> bool:
        """Aguarda a rota interna conter `trecho`. False no timeout."""
        import time

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if trecho in self._rota:
                return True
            self.sleep(0.5)
        return False

    def sleep(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def screenshot_para(self, caminho: str) -> None:
        """Grava um PNG do viewport — evidência de execução."""
        self.page.screenshot(path=caminho)
        logger.info("[PlaywrightSurface] screenshot: %s", caminho)
