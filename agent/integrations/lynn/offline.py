# -*- coding: utf-8 -*-
"""Leitura offline de respostas LYNN gravadas em disco (sem HTTP)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.integrations.lynn.http_client import _desembrulhar_lynn


@dataclass(frozen=True)
class LynnOfflinePayload:
    """Resultado de um ``{stem}.json`` ao lado do PDF em ``02_NF_Processadas_Lynn``."""

    caminho: Path
    extracao: dict[str, Any]
    classificacao: dict[str, Any] | None
    raw: dict[str, Any]


def desembrulhar_lynn(payload: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """API pública: extrai ``(extracao, classificacao)`` do envelope DTA/agente."""
    return _desembrulhar_lynn(payload)


def carregar_lynn_arquivo(caminho: str | Path) -> LynnOfflinePayload:
    """Lê JSON local e desembrulha ``extracao`` / ``classificacao``.

    Aceite (P0): ficheiros em ``02_NF_Processadas_Lynn\\*.json`` sem chamada HTTP.
    """
    path = Path(caminho)
    if not path.is_file():
        raise FileNotFoundError(f"JSON LYNN não encontrado: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"JSON LYNN inválido (esperado objeto): {path}")
    extracao, classificacao = desembrulhar_lynn(raw)
    if not isinstance(extracao, dict):
        raise ValueError(f"JSON LYNN sem bloco extracao utilizável: {path}")
    return LynnOfflinePayload(
        caminho=path,
        extracao=extracao,
        classificacao=classificacao if isinstance(classificacao, dict) else None,
        raw=raw,
    )
