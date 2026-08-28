"""Copia PDFs da pasta de rede TI (FSB) para a inbox `01_NF_Classificar`.

Busca **só por caminhos exactos** (nome ACB_OBJETO / candidatos) — sem
`iterdir` nem listagem de pastas na UNC.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from agent.integrations.fileshare.local import (
    LocalFileshareClient,
    _desembrulhar_pdf_se_multipart,
    _normalizar_candidatos,
)

logger = logging.getLogger(__name__)


def garantir_pdf_na_inbox(
    *,
    origem_root: str | Path,
    inbox: Path,
    cod_objeto: str,
    candidatos: list[str] | None = None,
    subdirs: list[str] | None = None,
) -> Path | None:
    """Localiza o PDF em `origem_root` e copia para `inbox` (não move).

    - `origem_root` vazio → None (noop; comportamento legado).
    - Se o ficheiro já existir na inbox → devolve o existente (não sobrescreve).
    - Se não existir na origem → `FileNotFoundError`.
    - `subdirs`: pastas relativas opcionais a tentar sem listar (ex. ANOMES).
    """
    raiz = str(origem_root or "").strip()
    if not raiz:
        return None

    inbox_path = Path(inbox)
    inbox_path.mkdir(parents=True, exist_ok=True)

    nomes = _normalizar_candidatos(cod_objeto, candidatos)
    if not nomes:
        raise ValueError("cod_objeto vazio e sem candidatos de nome PDF")

    # Já na inbox (mesmo nome) — evita ida à UNC.
    for nome in nomes:
        existente = inbox_path / nome
        try:
            if existente.is_file():
                logger.info("[stage_pdf] ja na inbox %s", existente.name)
                return existente
        except OSError:
            continue

    origem = _localizar_exacto(Path(raiz), nomes, subdirs=subdirs or [])
    destino = inbox_path / origem.name
    if destino.is_file():
        logger.info("[stage_pdf] ja na inbox %s", destino.name)
        return destino

    bruto = origem.read_bytes()
    payload = _desembrulhar_pdf_se_multipart(bruto)
    if payload != bruto:
        destino.write_bytes(payload)
    else:
        shutil.copy2(origem, destino)
    logger.info("[stage_pdf] copiado %s -> %s", origem.name, destino)
    return destino


def _localizar_exacto(
    raiz: Path,
    nomes: list[str],
    *,
    subdirs: list[str],
) -> Path:
    """Testa só `raiz/nome` e `raiz/subdir/nome` — zero listagens."""
    bases = [raiz]
    for rel in subdirs:
        rel_limpo = (rel or "").strip().strip("/\\")
        if rel_limpo:
            bases.append(raiz / rel_limpo)

    share = LocalFileshareClient(root=raiz)
    for base in bases:
        hit = share._procurar_em_base(base, nomes)
        if hit is not None:
            return hit

    raise FileNotFoundError(
        f"PDF nao encontrado em {raiz} (tentativas exactas: {nomes[:5]})"
    )
