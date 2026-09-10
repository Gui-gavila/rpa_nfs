"""Feriados nacionais federais do Brasil (sem dependência externa).

Calendário oficial (Leis 662/1949, 6.802/1980, 10.607/2002, 14.759/2023):
01/01, Paixão de Cristo, 21/04, 01/05, 07/09, 12/10, 02/11, 15/11,
20/11 (desde 2024) e 25/12.

Carnaval e Corpus Christi não entram: não são feriados federais.
"""

from __future__ import annotations

from datetime import date, timedelta


def pascoa(ano: int) -> date:
    """Páscoa gregoriana (algoritmo de Meeus/Jones/Butcher)."""
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados_nacionais(ano: int) -> frozenset[date]:
    """Conjunto de feriados federais no ano civil."""
    itens = [
        date(ano, 1, 1),
        pascoa(ano) - timedelta(days=2),
        date(ano, 4, 21),
        date(ano, 5, 1),
        date(ano, 9, 7),
        date(ano, 10, 12),
        date(ano, 11, 2),
        date(ano, 11, 15),
        date(ano, 12, 25),
    ]
    if ano >= 2024:
        itens.append(date(ano, 11, 20))
    return frozenset(itens)


def eh_fim_de_semana(dia: date) -> bool:
    return dia.weekday() >= 5


def eh_feriado_nacional(dia: date) -> bool:
    return dia in feriados_nacionais(dia.year)


def eh_dia_util(dia: date) -> bool:
    return not eh_fim_de_semana(dia) and not eh_feriado_nacional(dia)


def ajustar_para_dia_util_anterior(dia: date) -> date:
    """Recua até o último dia útil (sábado/domingo/feriado nacional).

    Cobre o pedido FSB: sáb→sexta (d-1), dom→sexta (d-2), feriado em
    segunda→sexta (d-3), feriado em ter–sex→véspera (e encadeia se preciso).
    """
    atual = dia
    for _ in range(16):
        if eh_dia_util(atual):
            return atual
        atual = atual - timedelta(days=1)
    return atual
