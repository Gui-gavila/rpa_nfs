"""Dublê fileshare: mapa cod_objeto → bytes ou path fonte."""

from __future__ import annotations

from pathlib import Path


class FakeFileshareClient:
    def __init__(
        self,
        arquivos: dict[str, bytes | Path] | None = None,
    ) -> None:
        self.arquivos = dict(arquivos or {})
        self.chamadas: list[str] = []
        self.candidatos_vistos: list[list[str]] = []

    def obter_pdf(
        self,
        cod_objeto: str,
        destino: str | Path,
        *,
        candidatos: list[str] | None = None,
    ) -> Path:
        self.chamadas.append(cod_objeto)
        self.candidatos_vistos.append(list(candidatos or []))
        chaves = [cod_objeto] + list(candidatos or [])
        fonte_key = None
        for chave in chaves:
            k = (chave or "").strip()
            if not k:
                continue
            if k in self.arquivos:
                fonte_key = k
                break
            if k.lower().endswith(".pdf") and k[:-4] in self.arquivos:
                fonte_key = k[:-4]
                break
        if fonte_key is None:
            raise FileNotFoundError(f"FakeFileshare: objeto {cod_objeto} ausente")
        dest = Path(destino)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fonte = self.arquivos[fonte_key]
        if isinstance(fonte, Path):
            dest.write_bytes(fonte.read_bytes())
        else:
            dest.write_bytes(fonte)
        return dest
