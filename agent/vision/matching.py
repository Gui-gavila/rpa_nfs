"""Motor de visão computacional — localização de elementos por template.

Este módulo é puro: opera sobre frames (`np.ndarray` BGR) e não conhece
Playwright. Quem captura o frame é a Surface; quem decide onde clicar é este
módulo.

Por que template matching e não seletores: o Protheus SmartClient Web
(canvas com protocolo binário, DOM vazio após o login) entrega apenas pixels.
Não há árvore de elementos para consultar.

Escala e DPR
------------
O matching é multi-escala, o que o torna tolerante a diferenças de resolução e
de DPI entre máquinas — um template capturado num monitor 1080p continua sendo
encontrado num 4K.

Coordenada é outra história. O frame pode estar em pixels físicos enquanto o
clique usa outra unidade (CSS num browser com devicePixelRatio 2, por exemplo).
A Surface expõe isso opcionalmente em `frame_scale` (pixels de frame por
unidade de clique); quem não expõe assume 1.0.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Escalas tentadas no needle, da mais provável para a menos.
# A ordem importa: o primeiro match acima do threshold não encerra a busca
# (procuramos o melhor), mas escalas comuns primeiro tornam o log mais legível.
ESCALAS_PADRAO: tuple[float, ...] = (1.0, 0.75, 1.25, 0.5, 1.5, 0.6, 1.75, 0.4, 2.0)

# Acima disto o needle é recortado ao centro. Templates grandes demais costumam
# incluir bordas com conteúdo dinâmico (datas, nome do usuário) que derrubam o
# score sem agregar informação de identificação.
MAX_NEEDLE_W = 480
MAX_NEEDLE_H = 360

POLL_SECONDS = 0.5


class SurfaceLike(Protocol):
    """O mínimo que este módulo precisa de uma Surface."""

    def capture(self) -> Any: ...
    def click(self, x: int, y: int) -> None: ...


class TemplateAusente(FileNotFoundError):
    """Arquivo de template não encontrado no diretório de recursos."""


@dataclass(frozen=True)
class Match:
    """Resultado de um casamento de template, em pixels de frame."""

    score: float
    top_left: tuple[int, int]
    escala: float
    tamanho: tuple[int, int]  # (largura, altura) do needle já escalado

    @property
    def centro(self) -> tuple[int, int]:
        w, h = self.tamanho
        return (self.top_left[0] + w // 2, self.top_left[1] + h // 2)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def carregar_template(nome: str, resources_dir: str | Path) -> np.ndarray:
    """Lê um template do diretório de recursos. Levanta TemplateAusente."""
    caminho = Path(resources_dir) / nome
    img = cv2.imread(str(caminho))
    if img is None:
        raise TemplateAusente(
            f"Template '{nome}' não encontrado em {resources_dir}.\n"
            f"  Recapture com: python scripts/capturar_templates.py"
        )
    return img


def preparar_needle(needle: np.ndarray, haystack: np.ndarray) -> np.ndarray:
    """Garante needle menor que o haystack, recortando ao centro se preciso.

    `matchTemplate` exige needle estritamente menor que a imagem de busca. Ao
    recortar preferimos o centro: as bordas de uma captura de tela é que
    carregam o conteúdo variável.
    """
    nh, nw = needle.shape[:2]
    hh, hw = haystack.shape[:2]

    if nh >= hh or nw >= hw:
        crop_h = min(nh, max(1, hh - 2))
        crop_w = min(nw, max(1, hw - 2))
        sy = (nh - crop_h) // 2
        sx = (nw - crop_w) // 2
        needle = needle[sy : sy + crop_h, sx : sx + crop_w]
        nh, nw = needle.shape[:2]

    if nw > MAX_NEEDLE_W or nh > MAX_NEEDLE_H:
        tw = min(nw, MAX_NEEDLE_W)
        th = min(nh, MAX_NEEDLE_H)
        sx = (nw - tw) // 2
        sy = (nh - th) // 2
        needle = needle[sy : sy + th, sx : sx + tw]

    return needle


# ---------------------------------------------------------------------------
# Casamento
# ---------------------------------------------------------------------------


def casar_multiescala(
    haystack_gray: np.ndarray,
    needle_gray: np.ndarray,
    escalas: Iterable[float] = ESCALAS_PADRAO,
) -> Match:
    """Melhor casamento do needle no haystack, testando várias escalas.

    Devolve sempre um Match — cabe a quem chama comparar `score` ao threshold.
    """
    hh, hw = haystack_gray.shape[:2]
    nh, nw = needle_gray.shape[:2]

    melhor = Match(score=0.0, top_left=(0, 0), escala=1.0, tamanho=(nw, nh))
    for escala in escalas:
        new_w = int(nw * escala)
        new_h = int(nh * escala)
        # Needle degenerado ou maior que o haystack: escala inaplicável.
        if new_w < 4 or new_h < 4 or new_w >= hw or new_h >= hh:
            continue
        redimensionado = cv2.resize(
            needle_gray, (new_w, new_h), interpolation=cv2.INTER_AREA
        )
        resultado = cv2.matchTemplate(haystack_gray, redimensionado, cv2.TM_CCOEFF_NORMED)
        _, score, _, top_left = cv2.minMaxLoc(resultado)
        if score > melhor.score:
            melhor = Match(
                score=float(score),
                top_left=(int(top_left[0]), int(top_left[1])),
                escala=float(escala),
                tamanho=(new_w, new_h),
            )
    return melhor


def _recortar_regiao(
    frame: np.ndarray,
    regiao: tuple[int, int, int, int] | None,
    frame_scale: float,
) -> tuple[np.ndarray, tuple[int, int]]:
    """Recorta o frame à região de busca. Devolve (recorte, deslocamento)."""
    if regiao is None:
        return frame, (0, 0)

    rx, ry, rw, rh = regiao
    fh, fw = frame.shape[:2]
    px = max(0, min(round(rx * frame_scale), fw - 1))
    py = max(0, min(round(ry * frame_scale), fh - 1))
    pw = max(1, min(round(rw * frame_scale), fw - px))
    ph = max(1, min(round(rh * frame_scale), fh - py))
    return frame[py : py + ph, px : px + pw], (px, py)


def localizar_no_frame(
    frame: np.ndarray,
    needle: np.ndarray,
    *,
    threshold: float = 0.75,
    regiao: tuple[int, int, int, int] | None = None,
    frame_scale: float = 1.0,
    escalas: Iterable[float] = ESCALAS_PADRAO,
) -> tuple[tuple[int, int] | None, Match]:
    """Procura o needle num frame já capturado.

    Devolve `(centro_em_coordenada_de_clique | None, match)`. O Match é
    devolvido mesmo em falha para que quem chama possa registrar o melhor score
    obtido — é a informação que permite calibrar o threshold depois.

    `regiao` é (x, y, w, h) em coordenadas de clique, útil quando outra parte
    da tela tem aparência parecida com o alvo.
    """
    recorte, (offset_x, offset_y) = _recortar_regiao(frame, regiao, frame_scale)
    needle = preparar_needle(needle, recorte)

    haystack_gray = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
    needle_gray = cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY)
    match = casar_multiescala(haystack_gray, needle_gray, escalas)

    if match.score < threshold:
        return None, match

    cx_frame, cy_frame = match.centro
    centro = (
        round((cx_frame + offset_x) / frame_scale),
        round((cy_frame + offset_y) / frame_scale),
    )
    return centro, match


# ---------------------------------------------------------------------------
# Operações sobre uma Surface
# ---------------------------------------------------------------------------


def _frame_scale(surface: Any) -> float:
    """Pixels de frame por unidade de clique. 1.0 quando a Surface não informa."""
    try:
        return float(getattr(surface, "frame_scale", 1.0) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def aguardar_template(
    surface: SurfaceLike,
    nome: str,
    *,
    resources_dir: str | Path,
    timeout_s: float = 30.0,
    threshold: float = 0.75,
    regiao: tuple[int, int, int, int] | None = None,
    escalas: Iterable[float] = ESCALAS_PADRAO,
    debug_dir: str | Path | None = None,
) -> tuple[int, int]:
    """Aguarda o template aparecer e devolve o centro em coordenada de clique.

    Levanta TimeoutError com o melhor score obtido e, quando `debug_dir` é
    informado, grava o último frame. Sem esse frame, diagnosticar um template
    que parou de casar depois de uma atualização do ERP é adivinhação.
    """
    needle = carregar_template(nome, resources_dir)
    escala_frame = _frame_scale(surface)
    melhor_score = 0.0
    ultimo_frame: np.ndarray | None = None

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        frame = surface.capture()
        if frame is None:
            time.sleep(POLL_SECONDS)
            continue
        ultimo_frame = frame

        centro, match = localizar_no_frame(
            frame,
            needle,
            threshold=threshold,
            regiao=regiao,
            frame_scale=escala_frame,
            escalas=escalas,
        )
        melhor_score = max(melhor_score, match.score)

        if centro is not None:
            logger.info(
                "[vision] '%s' em (%s,%s) score=%.2f escala=%.2f",
                nome, centro[0], centro[1], match.score, match.escala,
            )
            return centro
        time.sleep(POLL_SECONDS)

    destino = None
    if debug_dir is not None and ultimo_frame is not None:
        destino = Path(debug_dir) / f"debug_timeout_{Path(nome).stem}.png"
        destino.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(destino), ultimo_frame)

    raise TimeoutError(
        f"Template '{nome}' não detectado em {timeout_s}s "
        f"(melhor score={melhor_score:.2f}, threshold={threshold}).\n"
        + (f"  Frame do timeout: {destino}\n" if destino else "")
        + "  Compare o template com o frame para verificar escala e conteúdo."
    )


def clicar_template(
    surface: SurfaceLike,
    nome: str,
    *,
    resources_dir: str | Path,
    timeout_s: float = 30.0,
    threshold: float = 0.75,
    regiao: tuple[int, int, int, int] | None = None,
    debug_dir: str | Path | None = None,
) -> bool:
    """Localiza o template e clica no centro. False se não apareceu no prazo.

    Devolve booleano em vez de levantar porque a maioria dos passos de UI tem
    alternativa (tentar outro caminho, seguir sem o modal). Quem precisa de
    falha dura usa `aguardar_template` diretamente.
    """
    try:
        x, y = aguardar_template(
            surface,
            nome,
            resources_dir=resources_dir,
            timeout_s=timeout_s,
            threshold=threshold,
            regiao=regiao,
            debug_dir=debug_dir,
        )
    except TimeoutError as e:
        logger.warning("[vision] %s", e)
        return False
    surface.click(x, y)
    return True


def template_visivel(
    surface: SurfaceLike,
    nome: str,
    *,
    resources_dir: str | Path,
    threshold: float = 0.75,
    regiao: tuple[int, int, int, int] | None = None,
) -> bool:
    """Verificação instantânea, sem espera — para modais que podem não existir."""
    frame = surface.capture()
    if frame is None:
        return False
    needle = carregar_template(nome, resources_dir)
    centro, _ = localizar_no_frame(
        frame,
        needle,
        threshold=threshold,
        regiao=regiao,
        frame_scale=_frame_scale(surface),
    )
    return centro is not None


# ---------------------------------------------------------------------------
# Detecção por cor
# ---------------------------------------------------------------------------


def localizar_regiao_preenchida(
    frame: np.ndarray,
    *,
    cor_min: tuple[int, int, int],
    cor_max: tuple[int, int, int],
    min_w: int = 300,
    min_h: int = 30,
    max_w: int = 700,
    max_h: int = 90,
    fill_ratio_min: float = 0.50,
    frame_scale: float = 1.0,
) -> tuple[int, int] | None:
    """Centro da primeira região de cor sólida dentro dos limites de tamanho.

    Serve para elementos que o template matching não distingue bem: um botão
    preenchido e a borda fina de um campo podem ter a mesma cor e proporções
    parecidas. O que os separa é a densidade de preenchimento da bounding box —
    borda fina fica em 5–20%, botão sólido em 90–100%. Daí o `fill_ratio_min`.
    """
    mascara = cv2.inRange(frame, np.array(cor_min), np.array(cor_max))
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if not (min_w < w < max_w and min_h < h < max_h):
            continue
        preenchimento = np.count_nonzero(mascara[y : y + h, x : x + w]) / float(w * h)
        if preenchimento >= fill_ratio_min:
            logger.info(
                "[vision] região preenchida %sx%s fill=%.0f%%", w, h, preenchimento * 100
            )
            return (
                round((x + w // 2) / frame_scale),
                round((y + h // 2) / frame_scale),
            )
    return None


def aguardar_regiao_preenchida(
    surface: SurfaceLike,
    *,
    cor_min: tuple[int, int, int],
    cor_max: tuple[int, int, int],
    timeout_s: float = 10.0,
    **kwargs: Any,
) -> tuple[int, int]:
    """Versão com espera de `localizar_regiao_preenchida`. Levanta TimeoutError."""
    escala = _frame_scale(surface)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        frame = surface.capture()
        if frame is not None:
            centro = localizar_regiao_preenchida(
                frame, cor_min=cor_min, cor_max=cor_max, frame_scale=escala, **kwargs
            )
            if centro is not None:
                return centro
        time.sleep(0.3)
    raise TimeoutError(f"Região preenchida não detectada em {timeout_s}s")


# Vermelho do botão ativo do Protheus (BGR). Mantido aqui por ser calibrado
# contra a UI real, não por ser genérico.
VERMELHO_PROTHEUS = ((0, 0, 130), (100, 80, 220))
