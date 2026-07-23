"""Helpers de visão computacional compartilhados pelas Surfaces.

Toda a lógica de casamento vive em `agent.vision`; aqui só há delegação.
O mixin concentra as operações de alto nível (`locate_center` / `click_image`)
usadas pelo ProtheusAgent.

Aceita caminho completo de template (`resources/botao.png`) ou nome simples
resolvido contra `self.resources_dir`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from agent import vision

logger = logging.getLogger(__name__)


class VisionMixin:
    """Operações de CV sobre a própria Surface. Requer `capture()` e `click()`."""

    # Surfaces concretas podem sobrescrever; usado quando o template vem por nome.
    resources_dir: str | Path = "resources"

    def _resolver_template(self, image_path: str | Path) -> tuple[Path, str]:
        """Separa (diretório, nome) aceitando caminho completo ou nome simples."""
        p = Path(image_path)
        if p.parent != Path("."):
            return p.parent, p.name
        return Path(self.resources_dir), p.name

    def locate_center(
        self,
        image_path: str | Path,
        *,
        confidence: float = 0.7,
        scales: Iterable[float] | None = None,
    ) -> tuple[int, int] | None:
        """Centro do melhor casamento, ou None. Não espera nem levanta."""
        pasta, nome = self._resolver_template(image_path)
        frame = self.capture()
        if frame is None:
            return None
        try:
            needle = vision.carregar_template(nome, pasta)
        except vision.TemplateAusente as e:
            logger.error("[Surface] %s", e)
            return None
        centro, match = vision.localizar_no_frame(
            frame,
            needle,
            threshold=confidence,
            frame_scale=getattr(self, "frame_scale", 1.0),
            escalas=scales or vision.ESCALAS_PADRAO,
        )
        if centro is None:
            logger.debug(
                "[Surface] casamento fraco %s score=%.3f conf=%.2f",
                nome, match.score, confidence,
            )
        return centro

    def click_image(
        self,
        image_path: str | Path,
        *,
        confidence: float = 0.7,
        clicks: int = 1,
        button: str = "left",
        timeout_s: float = 15.0,
        offset_x: int = 0,
        offset_y: int = 0,
        scales: Iterable[float] | None = None,
    ) -> bool:
        """Localiza o template e clica. False se não apareceu no prazo.

        `offset_x`/`offset_y` deslocam o clique em relação ao centro — usado
        quando o template é uma âncora estável (um rótulo) e o alvo real é o
        campo ao lado dele.
        """
        import time

        pasta, nome = self._resolver_template(image_path)
        if not (pasta / nome).is_file():
            logger.error("[Surface] template ausente: %s", pasta / nome)
            return False

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            pos = self.locate_center(pasta / nome, confidence=confidence, scales=scales)
            if pos:
                x, y = pos[0] + offset_x, pos[1] + offset_y
                self.click(x, y, clicks=clicks, button=button)
                logger.info("[Surface] click_image %s @(%s,%s)", nome, x, y)
                return True
            time.sleep(0.5)

        logger.warning("[Surface] template não encontrado em %ss: %s", timeout_s, nome)
        return False

    def wait_image(
        self,
        image_path: str | Path,
        *,
        confidence: float = 0.75,
        timeout_s: float = 30.0,
        region: tuple[int, int, int, int] | None = None,
        debug_dir: str | Path | None = None,
    ) -> tuple[int, int]:
        """Aguarda o template e devolve o centro. Levanta TimeoutError."""
        pasta, nome = self._resolver_template(image_path)
        return vision.aguardar_template(
            self,
            nome,
            resources_dir=pasta,
            timeout_s=timeout_s,
            threshold=confidence,
            regiao=region,
            debug_dir=debug_dir,
        )

    def image_visible(
        self,
        image_path: str | Path,
        *,
        confidence: float = 0.75,
        region: tuple[int, int, int, int] | None = None,
    ) -> bool:
        """Verificação instantânea — para modais que podem legitimamente não existir."""
        pasta, nome = self._resolver_template(image_path)
        try:
            return vision.template_visivel(
                self, nome, resources_dir=pasta, threshold=confidence, regiao=region
            )
        except vision.TemplateAusente as e:
            logger.error("[Surface] %s", e)
            return False
