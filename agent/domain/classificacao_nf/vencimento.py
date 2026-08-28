"""Cálculo de data de vencimento (RN-08 + vencimento especial)."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping


def _norm(valor: Any) -> str:
    return str(valor or "").strip()


def _parse_data(valor: Any) -> date | None:
    if isinstance(valor, date):
        return valor
    texto = _norm(valor)
    if not texto:
        return None
    # ISO ou dd/mm/yyyy
    if "/" in texto:
        dia, mes, ano = texto.split("/", 2)
        return date(int(ano), int(mes), int(dia))
    return date.fromisoformat(texto)


def _ultimo_dia_mes(ano: int, mes: int) -> int:
    if mes == 12:
        seguinte = date(ano + 1, 1, 1)
    else:
        seguinte = date(ano, mes + 1, 1)
    return (seguinte.toordinal() - 1) - date(ano, mes, 1).toordinal() + 1


def _dia_no_mes(ano: int, mes: int, dia: int) -> date:
    return date(ano, mes, min(dia, _ultimo_dia_mes(ano, mes)))


def vencimento_por_nivel(nivel: int, referencia: date) -> date:
    """Níveis 1–3: dia 25 do mês vigente; nível 4: dia 5 do mês subsequente."""
    if int(nivel) == 4:
        if referencia.month == 12:
            return date(referencia.year + 1, 1, 5)
        return date(referencia.year, referencia.month + 1, 5)
    return _dia_no_mes(referencia.year, referencia.month, 25)


def vencimento_especial_fornecedor(
    codigo_fornecedor: str,
    tabela: Iterable[Mapping[str, Any]],
) -> date | None:
    """Convenção: codigo_fornecedor, data_vencimento."""
    codigo = _norm(codigo_fornecedor)
    for linha in tabela:
        if _norm(linha.get("codigo_fornecedor") or linha.get("fornecedor")) != codigo:
            continue
        return _parse_data(linha.get("data_vencimento") or linha.get("vencimento"))
    return None


def calcular_vencimento(
    *,
    nivel: int,
    codigo_fornecedor: str,
    referencia: date,
    tabela_especial: Iterable[Mapping[str, Any]] | None = None,
) -> date:
    """Prioriza vencimento especial do fornecedor; senão regra por nível."""
    if tabela_especial is not None:
        especial = vencimento_especial_fornecedor(codigo_fornecedor, tabela_especial)
        if especial is not None:
            return especial
    return vencimento_por_nivel(nivel, referencia)
