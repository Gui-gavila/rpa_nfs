"""Pastas operacionais do classificador NF (FOLDER_FILES_AGENT_LYNN 01–05 + ANOMES)."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from shutil import move
from typing import Any

DIR_CLASSIFICAR = "01_NF_Classificar"
DIR_PROCESSAR = DIR_CLASSIFICAR  # alias: inbox dos PDFs enviados ao LYNN
DIR_PROCESSADAS = "02_NF_Processadas_Lynn"
DIR_CLASSIFICADAS = "03_Classificadas_Protheus"
DIR_LOGS = "04_Logs"
DIR_SCREENSHOT = "05_Screenshots"
PASTAS_OPERACIONAIS = frozenset(
    {
        DIR_PROCESSAR,
        DIR_PROCESSADAS,
        DIR_CLASSIFICADAS,
        DIR_LOGS,
        DIR_SCREENSHOT,
    }
)
CONTROLE_XLSX_NOME = "ControleClassificacao.xlsx"
# Alias: pasta de destino após tratar a NF (antes: NF_Processadas).
NF_PROCESSADAS = DIR_PROCESSADAS


def anomes(referencia: date | None = None) -> str:
    """YYYYMM da data de execução (não da emissão da NF)."""
    dia = referencia or date.today()
    return f"{dia.year:04d}{dia.month:02d}"


def montar_nome_screenshot(contexto: str, *, when: datetime | None = None) -> str:
    """`YYYY-MM-DD-HH-MM-SS_{contexto}.png` — ocorrência no nome, identificável no log."""
    stamp = (when or datetime.now()).strftime("%Y-%m-%d-%H-%M-%S")
    bruto = (contexto or "erro").strip()
    if bruto.lower().endswith(".png"):
        bruto = bruto[:-4]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", bruto).strip("._-") or "erro"
    return f"{stamp}_{slug[:80]}.png"


def pasta_screenshot_falha(
    explicit: str | Path | None = None,
    *,
    referencia: date | None = None,
    criar: bool = True,
) -> Path:
    """Pasta dos PNG de UI: arg > SCREENSHOTS_DIR > 05_Screenshots/ANOMES > ./screenshots."""
    if explicit:
        pasta = Path(explicit)
    else:
        env = (os.getenv("SCREENSHOTS_DIR") or "").strip()
        if env:
            pasta = Path(env)
        else:
            pasta = _pasta_screenshot_classificador(referencia)
    if criar:
        pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _pasta_screenshot_classificador(referencia: date | None = None) -> Path:
    try:
        from agent import config

        root = (
            getattr(config, "FOLDER_FILES_AGENT_LYNN", "")
            or getattr(config, "FOLDER_ROOT_AGENT_LYNN", "")
            or getattr(config, "CLASSIFICADOR_NF_ROOT", "")
            or ""
        ).strip()
        env_root = (
            os.getenv("FOLDER_FILES_AGENT_LYNN")
            or os.getenv("FOLDER_ROOT_AGENT_LYNN")
            or ""
        ).strip()
        if not root and env_root:
            root = env_root
        if not root:
            return Path("screenshots")
        base = Path(root)
        if not base.exists() and not env_root:
            return Path("screenshots")
        return garantir_pastas(base, referencia=referencia)["screenshot_anomes"]
    except Exception:
        return Path("screenshots")


def resolver_caminhos(
    *,
    root: str | Path,
    work_dir: str | Path = "",
    checkpoint_dir: str | Path = "",
    controle_xlsx: str | Path = "",
    referencia: date | None = None,
) -> dict[str, str]:
    """Deriva 01–05, subpastas ANOMES e o Excel de controle a partir do root.

    Paths explícitos (não vazios) vencem a derivação.
    """
    base = Path(str(root).strip() or ".")
    mes = anomes(referencia)
    processar = base / DIR_PROCESSAR
    processadas = base / DIR_PROCESSADAS
    classificadas = base / DIR_CLASSIFICADAS
    logs = base / DIR_LOGS
    screenshot = base / DIR_SCREENSHOT
    processar_anomes = processar / mes
    processadas_anomes = processadas / mes
    classificadas_anomes = classificadas / mes
    work = str(work_dir or "").strip()
    ck = str(checkpoint_dir or "").strip()
    xlsx = str(controle_xlsx or "").strip()
    return {
        "root": str(base),
        "processar": str(processar),
        "processadas": str(processadas),
        "classificadas": str(classificadas),
        "logs": str(logs),
        "screenshot": str(screenshot),
        "processar_anomes": str(processar_anomes),
        "processadas_anomes": str(processadas_anomes),
        "classificadas_anomes": str(classificadas_anomes),
        "logs_anomes": str(logs / mes),
        "screenshot_anomes": str(screenshot / mes),
        "work_dir": work or str(processar_anomes),
        "checkpoint_dir": ck or str(processadas),
        "controle_xlsx": xlsx or str(processadas / CONTROLE_XLSX_NOME),
    }


def caminhos_de_config(config: Any | None = None) -> dict[str, str]:
    """Resolve paths a partir de `agent.config` (ou objeto injetado nos testes)."""
    if config is None:
        from agent import config as config
    return resolver_caminhos(
        root=(
            getattr(config, "FOLDER_FILES_AGENT_LYNN", "")
            or getattr(config, "FOLDER_ROOT_AGENT_LYNN", "")
            or getattr(config, "CLASSIFICADOR_NF_ROOT", "")
        ),
        work_dir=getattr(config, "CLASSIFICAR_NF_WORK_DIR", ""),
        checkpoint_dir=getattr(config, "CLASSIFICAR_NF_CHECKPOINT_DIR", ""),
        controle_xlsx=getattr(config, "CLASSIFICAR_NF_CONTROLE_XLSX", ""),
    )


def garantir_pastas(
    root: str | Path,
    *,
    referencia: date | None = None,
) -> dict[str, Path]:
    """Cria 01–05 e as subpastas ANOMES. Devolve as pastas criadas."""
    mes = anomes(referencia)
    base = Path(root)
    criadas: dict[str, Path] = {}
    for chave, nome in (
        ("processar", DIR_PROCESSAR),
        ("processadas", DIR_PROCESSADAS),
        ("classificadas", DIR_CLASSIFICADAS),
        ("logs", DIR_LOGS),
        ("screenshot", DIR_SCREENSHOT),
    ):
        pasta = base / nome
        anomes_dir = pasta / mes
        anomes_dir.mkdir(parents=True, exist_ok=True)
        criadas[chave] = pasta
        criadas[f"{chave}_anomes"] = anomes_dir
    return criadas


def pasta_trabalho_pdf(
    config: Any | None = None,
    *,
    referencia: date | None = None,
) -> Path:
    """Pasta da inbox em curso: `01_NF_Classificar/ANOMES`, salvo WORK_DIR explícito.

    Não cria a árvore 01–05 quando WORK_DIR está definido (testes isolados).
    """
    if config is None:
        from agent import config as config
    work = str(getattr(config, "CLASSIFICAR_NF_WORK_DIR", "") or "").strip()
    root = str(
        getattr(config, "FOLDER_FILES_AGENT_LYNN", "")
        or getattr(config, "FOLDER_ROOT_AGENT_LYNN", "")
        or getattr(config, "CLASSIFICADOR_NF_ROOT", "")
        or ""
    ).strip()
    if work:
        destino = Path(work)
        destino.mkdir(parents=True, exist_ok=True)
        return destino
    criadas = garantir_pastas(root, referencia=referencia)
    return criadas["processar_anomes"]


def pasta_processadas_de_trabalho(work_dir: str | Path) -> Path | None:
    """`02_NF_Processadas_Lynn/{ANOMES}` irmão de `01_NF_Classificar/{ANOMES}`; senão None."""
    work = Path(work_dir)
    if work.parent.name != DIR_PROCESSAR:
        return None
    return work.parent.parent / DIR_PROCESSADAS / work.name


def mover_pdf_para_processadas(
    pdf_path: str | Path,
    *,
    work_dir: str | Path,
    nome_destino: str | None = None,
) -> Path | None:
    """Move o PDF da inbox 01/ANOMES para 02/ANOMES (opcionalmente já no nome-stem).

    Fora do layout ops, só renomeia no sítio se `nome_destino` for dado.
    """
    origem = Path(pdf_path)
    if not origem.is_file():
        return None
    dest_dir = pasta_processadas_de_trabalho(work_dir)
    if dest_dir is None:
        if not nome_destino or origem.name == nome_destino:
            return origem
        dest = origem.parent / nome_destino
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / (nome_destino or origem.name)
    if dest.resolve() == origem.resolve():
        return origem
    if dest.exists():
        dest.unlink()
    move(str(origem), str(dest))
    return dest



def mover_para_classificadas_protheus(
    pdf_path: str | Path | None,
    *,
    referencia: date | None = None,
) -> Path | None:
    """Após classificação no Protheus: move PDF + JSON de 02/ANOMES → 03/ANOMES.

    Só age se o PDF estiver sob `02_NF_Processadas_Lynn`. O JSON irmão
    `{stem}.json` acompanha quando existir.
    """
    del referencia  # ANOMES vem da pasta do PDF (mês em que o LYNN processou).
    if not pdf_path:
        return None
    origem = Path(pdf_path)
    if not origem.is_file():
        return None

    # Esperado: .../02_NF_Processadas_Lynn/{ANOMES}/{stem}.pdf
    if origem.parent.parent.name != DIR_PROCESSADAS:
        return None
    mes = origem.parent.name
    dest_dir = origem.parent.parent.parent / DIR_CLASSIFICADAS / mes
    dest_dir.mkdir(parents=True, exist_ok=True)

    json_origem = origem.with_suffix(".json")

    dest_pdf = dest_dir / origem.name
    if dest_pdf.exists() and dest_pdf.resolve() != origem.resolve():
        dest_pdf.unlink()
    move(str(origem), str(dest_pdf))

    if json_origem.is_file():
        dest_json = dest_dir / json_origem.name
        if dest_json.exists() and dest_json.resolve() != json_origem.resolve():
            dest_json.unlink()
        move(str(json_origem), str(dest_json))

    return dest_pdf


def gravar_resposta_lynn(pdf_path: str | Path, payload: Any) -> Path:
    """Grava `{stem}.json` ao lado do PDF (retorno bruto ou serializado do LYNN)."""
    dest = Path(pdf_path).with_suffix(".json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return dest
