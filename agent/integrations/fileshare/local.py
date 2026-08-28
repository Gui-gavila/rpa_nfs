"""Fileshare local: candidatos FSB + fallback `{cod_objeto}.pdf`.

Lab T2 tipico: inbox `{FOLDER_FILES_AGENT_LYNN}/01_NF_Classificar`
(raiz + subpastas imediatas, ex. 202608).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalFileshareClient:
    def __init__(self, *, root: str | Path) -> None:
        self.root = Path(root)

    def _bases_busca(self) -> list[Path]:
        """Raiz + subpastas imediatas (ex.: AgentLynn/202607), sem 01–04 ops."""
        from agent.jobs.classificar_nf.caminhos import PASTAS_OPERACIONAIS

        bases = [self.root]
        try:
            for filho in sorted(self.root.iterdir()):
                if not filho.is_dir() or filho.name.startswith("."):
                    continue
                if filho.name in PASTAS_OPERACIONAIS:
                    continue
                bases.append(filho)
        except OSError:
            pass
        return bases

    def localizar_pdf(
        self,
        cod_objeto: str,
        *,
        candidatos: list[str] | None = None,
        apenas_raiz: bool = False,
    ) -> Path:
        """Devolve o PDF na inbox/share sem copiar.

        `apenas_raiz=True`: só caminhos exactos na raiz (sem `iterdir`).
        Caso contrário: raiz e depois subpastas imediatas (inbox local pequena).
        """
        nomes = _normalizar_candidatos(cod_objeto, candidatos)
        if not nomes:
            raise ValueError("cod_objeto vazio e sem candidatos de nome PDF")

        hit = self._procurar_em_base(self.root, nomes)
        if hit is not None:
            return hit
        if apenas_raiz:
            raise FileNotFoundError(
                f"PDF nao encontrado em {self.root} (tentativas: {nomes[:5]})"
            )

        for base in self._bases_busca():
            try:
                if base.resolve() == self.root.resolve():
                    continue
            except OSError:
                pass
            hit = self._procurar_em_base(base, nomes)
            if hit is not None:
                return hit
        raise FileNotFoundError(
            f"PDF nao encontrado em {self.root} (tentativas: {nomes[:5]})"
        )

    def _procurar_em_base(self, base: Path, nomes: list[str]) -> Path | None:
        for nome in nomes:
            stem = nome[:-4] if nome.lower().endswith(".pdf") else nome
            for cand in (
                base / nome,
                base / f"{stem}.pdf",
                base / stem / f"{stem}.pdf",
                base / stem / nome,
            ):
                try:
                    if cand.is_file():
                        return cand
                except OSError:
                    continue
        return None

    def obter_pdf(
        self,
        cod_objeto: str,
        destino: str | Path,
        *,
        candidatos: list[str] | None = None,
    ) -> Path:
        origem = self.localizar_pdf(cod_objeto, candidatos=candidatos)
        dest = Path(destino)
        dest.parent.mkdir(parents=True, exist_ok=True)
        bruto = origem.read_bytes()
        payload = _desembrulhar_pdf_se_multipart(bruto)
        if dest.resolve() == origem.resolve():
            if payload != bruto:
                logger.warning(
                    "[Fileshare] envelope multipart na origem; nao altera o share %s",
                    origem,
                )
            return origem
        if payload != bruto:
            dest.write_bytes(payload)
            logger.info(
                "[Fileshare] copiado PDF interno (multipart) %s -> %s", origem, dest
            )
        else:
            shutil.copy2(origem, dest)
            logger.info("[Fileshare] copiado %s -> %s", origem, dest)
        return dest


def _desembrulhar_pdf_se_multipart(raw: bytes) -> bytes:
    """Se o ficheiro for POST multipart com PDF interno, devolve só o PDF.

    O share FSB por vezes grava o corpo WebKit (`WebKitFormBoundary`) em vez
    do `%PDF` na raiz. Não inventa conteúdo: recorta `%PDF-` … `%%EOF`.
    """
    if not raw or raw.lstrip().startswith(b"%PDF-"):
        return raw
    if not raw.startswith(b"--"):
        return raw
    if b"%PDF-" not in raw:
        return raw
    if not (
        b"WebKitFormBoundary" in raw
        or b"Content-Type: application/pdf" in raw
        or b"Content-Disposition:" in raw
    ):
        return raw
    inicio = raw.find(b"%PDF-")
    fim = raw.rfind(b"%%EOF")
    if inicio < 0 or fim < inicio:
        return raw
    interno = raw[inicio : fim + 5]
    if interno.startswith(b"%PDF-") and interno.endswith(b"%%EOF"):
        return interno
    return raw


def _normalizar_candidatos(
    cod_objeto: str, candidatos: list[str] | None
) -> list[str]:
    out: list[str] = []
    for raw in list(candidatos or []) + ([cod_objeto] if cod_objeto else []):
        nome = (raw or "").strip()
        if not nome:
            continue
        if not nome.lower().endswith(".pdf"):
            nome = f"{nome}.pdf"
        if nome not in out:
            out.append(nome)
    return out
