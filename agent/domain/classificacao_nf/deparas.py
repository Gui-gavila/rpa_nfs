"""Deparas fiscais em memória / CSV (RN-05..07)."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Item da Lei 13.701/03: "17.02" ou subitem "17.02.01" (o subitem é descartado).
_ITEM_LEI = re.compile(r"^(\d{1,2}\.\d{2})(?:\.\d{2})?$")


def _norm(valor: Any) -> str:
    return str(valor or "").strip()


def _flag(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    texto = _norm(valor).casefold()
    if texto in ("1", "true", "sim", "s", "yes", "y", "x"):
        return True
    if texto in ("0", "false", "nao", "não", "n", "no", ""):
        return False
    return bool(texto)


def carregar_tabela_csv(caminho: str | Path) -> list[dict[str, str]]:
    """Carrega CSV com cabeçalho; encoding UTF-8."""
    path = Path(caminho)
    with path.open(encoding="utf-8", newline="") as fh:
        leitor = csv.DictReader(fh)
        return [{k: (v or "").strip() for k, v in linha.items()} for linha in leitor]


@dataclass
class TabelasDepara:
    """Tabelas de referência fornecidas pela Fiscal (conteúdo externo ao Git)."""

    natureza_despesa: Sequence[Mapping[str, Any]] = field(default_factory=list)
    codigo_servico: Sequence[Mapping[str, Any]] = field(default_factory=list)
    natureza_rendimento: Sequence[Mapping[str, Any]] = field(default_factory=list)
    vencimento_especial: Sequence[Mapping[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class NaturezaDespesaResolvida:
    natureza_despesa: str
    codigo_retencao: str | None = None


def resolver_codigo_servico(
    codigo_extraido: str,
    tabela: Iterable[Mapping[str, Any]],
) -> str | None:
    """Devolve código atualizado se houver depara; senão o próprio código se já válido.

    Convenção CSV/dict:
      codigo_antigo, codigo_novo
    Se `codigo_extraido` já for um `codigo_novo` conhecido, mantém.
    Se não houver linha e a tabela estiver vazia, devolve o extraído.
    Se a tabela tiver linhas e o código não constar (nem antigo nem novo), None.
    """
    codigo = _norm(codigo_extraido)
    if not codigo:
        return None

    linhas = list(tabela)
    if not linhas:
        return codigo

    novos: set[str] = set()
    for linha in linhas:
        antigo = _norm(linha.get("codigo_antigo") or linha.get("codigo_servico_antigo"))
        novo = _norm(linha.get("codigo_novo") or linha.get("codigo_servico_novo"))
        if novo:
            novos.add(novo)
        if antigo == codigo and novo:
            return novo

    if codigo in novos:
        return codigo
    return None


def resolver_natureza_despesa(
    codigo_servico: str,
    *,
    tem_iss_a_recolher: bool,
    tem_irrf: bool,
    tem_pcc: bool,
    tabela: Iterable[Mapping[str, Any]],
) -> NaturezaDespesaResolvida | None:
    """Localiza natureza + retenção pelo serviço e perfil de impostos.

    Convenção CSV/dict:
      codigo_servico, iss_a_recolher, irrf, pcc, natureza_despesa, codigo_retencao
    Flags vazias na tabela = curingas (aceitam qualquer valor).
    """
    codigo = _norm(codigo_servico)
    for linha in tabela:
        if _norm(linha.get("codigo_servico")) != codigo:
            continue
        iss_cell = linha.get("iss_a_recolher", linha.get("iss"))
        irrf_cell = linha.get("irrf")
        pcc_cell = linha.get("pcc")
        if _norm(iss_cell) and _flag(iss_cell) != tem_iss_a_recolher:
            continue
        if _norm(irrf_cell) and _flag(irrf_cell) != tem_irrf:
            continue
        if _norm(pcc_cell) and _flag(pcc_cell) != tem_pcc:
            continue
        natureza = _norm(linha.get("natureza_despesa") or linha.get("natureza"))
        if not natureza:
            continue
        retencao = _norm(linha.get("codigo_retencao")) or None
        return NaturezaDespesaResolvida(natureza, retencao)
    return None


def _celula(linha: Mapping[str, Any], *chaves: str) -> str:
    for chave in chaves:
        if chave in linha and linha[chave] is not None:
            return _norm(linha[chave])
        alvo = chave.casefold()
        for k, v in linha.items():
            if str(k).casefold() == alvo and v is not None:
                return _norm(v)
    return ""


def resolver_natureza_rendimento(
    codigo_servico: str,
    tabela: Iterable[Mapping[str, Any]],
) -> str | None:
    """Convenção: codigo_servico/Item + natureza_rendimento (xlsx FSB)."""
    codigo = _norm(codigo_servico)
    for linha in tabela:
        cod_linha = _celula(linha, "codigo_servico", "Item", "item", "codigo")
        if cod_linha != codigo:
            continue
        natureza = _celula(
            linha,
            "natureza_rendimento",
            "Natureza de Rendimento",
            "natureza",
        )
        if natureza:
            return natureza
    return None


def _item_lei(valor: str) -> str | None:
    texto = _norm(valor)
    achado = _ITEM_LEI.fullmatch(texto)
    if not achado:
        return None
    return achado.group(1)


def normalizar_cod_tributacao(
    codigo: str,
    tabela_rendimento: Iterable[Mapping[str, Any]] = (),
) -> str | None:
    """Reduz COD_TRIBUTACAO ao item da Lei 13.701/03 (``xx.xx``).

    Item já no formato da lei (``17.02`` ou ``17.02.01``) não consulta de/para.
    Código de serviço numérico consulta a coluna item da Natureza de Rendimento.
    Sem linha correspondente, devolve None.
    """
    bruto = _norm(codigo)
    if not bruto:
        return None
    item = _item_lei(bruto)
    if item:
        return item
    if not bruto.isdigit():
        return None
    for linha in tabela_rendimento:
        codigo_linha = _celula(
            linha,
            "codigo",
            "codigo_servico",
            "Codigo",
            "Codigo de Servico",
            "Código de Serviço",
        )
        if codigo_linha != bruto:
            continue
        item_linha = _item_lei(
            _celula(linha, "item", "Item", "item_lei", "Item da Lei", "Item Lei")
        )
        if item_linha and item_linha != bruto:
            return item_linha
    return None
