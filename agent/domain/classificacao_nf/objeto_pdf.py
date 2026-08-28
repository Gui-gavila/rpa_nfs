"""Chave AC9 e nomes de PDF da base de conhecimento (FSB / .docs/projeto)."""

from __future__ import annotations

from agent.domain.classificacao_nf.modelos import NotaErp


def _fix(valor: str, largura: int, *, numerico: bool = False) -> str:
    texto = (valor or "").strip()
    if len(texto) > largura:
        return texto[-largura:] if numerico else texto[:largura]
    if numerico or texto.isdigit():
        return texto.zfill(largura)
    return texto.ljust(largura)


def acb_filial_de_filent(filial: str) -> str:
    """ACB_FILIAL no ColetarPDF FSB: 2 primeiros dígitos de AC9_FILENT (ex. 2301→23)."""
    return (filial or "").strip()[:2]


def montar_ac9_codent(
    *,
    numero_nf: str,
    serie_nf: str,
    codigo_fornecedor: str,
    codigo_loja: str,
) -> str:
    """AC9_CODENT = DOC(9)+SERIE(3)+FORNECE(6)+LOJA(2) — Coletar_PDF.docx."""
    return (
        _fix(numero_nf, 9, numerico=True)
        + _fix(serie_nf, 3)
        + _fix(codigo_fornecedor, 6)
        + _fix(codigo_loja, 2, numerico=True)
    )


def montar_ac9_codent_de_nota(nota: NotaErp) -> str:
    return montar_ac9_codent(
        numero_nf=nota.numero_nf,
        serie_nf=nota.serie_nf,
        codigo_fornecedor=nota.codigo_fornecedor,
        codigo_loja=nota.codigo_loja,
    )


def nome_arquivo_pdf_fsb(
    *,
    filial_codigo: str,
    codigo_fornecedor: str,
    codigo_loja: str,
    numero_nf: str,
    serie_nf: str,
) -> str:
    """Padrão das amostras: `{filial}_{forn}-{loja}_{doc}{serie}.pdf`."""
    filial = (filial_codigo or "").strip()
    forn = (codigo_fornecedor or "").strip()
    loja = (codigo_loja or "").strip()
    doc = _fix(numero_nf, 9, numerico=True)
    serie = (serie_nf or "").strip()
    return f"{filial}_{forn}-{loja}_{doc}{serie}.pdf"


def nome_arquivo_pdf_fsb_de_nota(nota: NotaErp) -> str:
    return nome_arquivo_pdf_fsb(
        filial_codigo=nota.filial_codigo,
        codigo_fornecedor=nota.codigo_fornecedor,
        codigo_loja=nota.codigo_loja,
        numero_nf=nota.numero_nf,
        serie_nf=nota.serie_nf,
    )


def candidatos_nomes_pdf(nota: NotaErp, *, acb_objeto: str = "") -> list[str]:
    """Ordem: ACB_OBJETO (ColetarPDF) → naming FSB D3 → `{codent}.pdf`."""
    nomes: list[str] = []
    acb = (acb_objeto or "").strip()
    if acb:
        nome_acb = acb if acb.lower().endswith(".pdf") else f"{acb}.pdf"
        nomes.append(nome_acb)
    if (
        (nota.filial_codigo or "").strip()
        and (nota.codigo_fornecedor or "").strip()
        and (nota.codigo_loja or "").strip()
        and (nota.numero_nf or "").strip()
        and (nota.serie_nf or "").strip()
    ):
        nome_fsb = nome_arquivo_pdf_fsb_de_nota(nota)
        if nome_fsb not in nomes:
            nomes.append(nome_fsb)
    cod = (nota.cod_objeto or "").strip()
    if not cod and (nota.serie_nf or "").strip() and (nota.codigo_loja or "").strip():
        cod = montar_ac9_codent_de_nota(nota)
    if cod:
        nome_cod = cod if cod.lower().endswith(".pdf") else f"{cod}.pdf"
        if nome_cod not in nomes:
            nomes.append(nome_cod)
    return nomes
