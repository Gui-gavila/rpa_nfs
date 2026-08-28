"""Dublê LYNN: devolve NotaPdf pré-carregada por nome de ficheiro ou default."""

from __future__ import annotations

from pathlib import Path

from agent.domain.classificacao_nf.modelos import NotaPdf


class FakeLynnClient:
    def __init__(
        self,
        por_nome: dict[str, NotaPdf] | None = None,
        *,
        default: NotaPdf | None = None,
    ) -> None:
        self.por_nome = dict(por_nome or {})
        self.default = default
        self.chamadas: list[str] = []

    def extrair_nf(self, pdf_path: str | Path) -> NotaPdf:
        path = Path(pdf_path)
        self.chamadas.append(str(path))
        if path.name in self.por_nome:
            return self.por_nome[path.name]
        if self.default is not None:
            return self.default
        raise KeyError(f"FakeLynnClient sem fixture para {path.name}")
