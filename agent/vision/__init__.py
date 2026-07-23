"""Camada de visão computacional — localização de elementos por template.

Motor único, compartilhado por todas as Surfaces (browser, X11, desktop).
Opera sobre frames BGR e devolve coordenadas de clique; não conhece o backend
que produziu o pixel.
"""

from __future__ import annotations

from agent.vision.matching import (
    ESCALAS_PADRAO,
    VERMELHO_PROTHEUS,
    Match,
    TemplateAusente,
    aguardar_regiao_preenchida,
    aguardar_template,
    carregar_template,
    casar_multiescala,
    clicar_template,
    localizar_no_frame,
    localizar_regiao_preenchida,
    preparar_needle,
    template_visivel,
)

__all__ = [
    "ESCALAS_PADRAO",
    "VERMELHO_PROTHEUS",
    "Match",
    "TemplateAusente",
    "aguardar_regiao_preenchida",
    "aguardar_template",
    "carregar_template",
    "casar_multiescala",
    "clicar_template",
    "localizar_no_frame",
    "localizar_regiao_preenchida",
    "preparar_needle",
    "template_visivel",
]
