"""Filtro de layouts NFS-e (CR §4.3 / F6).

Processa só DANFSe nacional (reforma jan/2026), SP e DF. Qualquer outra
prefeitura ou documento que não seja NFS-e para em Não Classificado, sem UI.
"""

from __future__ import annotations

import unicodedata

from agent.domain.classificacao_nf.modelos import ClassificacaoLynn
from agent.domain.classificacao_nf.status import MOTIVOS

LAYOUTS_PERMITIDOS = frozenset({"nacional", "saopaulo", "brasilia"})


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in decomposto if not unicodedata.combining(ch))


def normalizar_layout(valor: str | None) -> str:
    """Compara o LAYOUT do LYNN sem acento, espaço ou maiúscula."""
    if not valor:
        return ""
    texto = _sem_acento(valor.strip()).casefold()
    return texto.replace(" ", "").replace("-", "").replace("_", "")


def layout_permitido(layout: str | None) -> bool:
    """True para Nacional, SaoPaulo e Brasilia (tokens do prompt LYNN V2)."""
    return normalizar_layout(layout) in LAYOUTS_PERMITIDOS


def motivo_recusa_layout_ou_tipo(clf: ClassificacaoLynn) -> str | None:
    """Motivo canónico se a NF não deve ir ao MATA103; None se pode seguir."""
    if clf.tipo_nf_pdf is False:
        return MOTIVOS.TIPO_DIVERGENTE
    if not layout_permitido(clf.layout):
        return MOTIVOS.LAYOUT_NAO_SUPORTADO
    return None
