"""Orquestra RN-04 + vencimento; classificação fiscal preferencialmente via LYNN V7."""

from __future__ import annotations

from datetime import date

from agent.domain.classificacao_nf.deparas import (
    TabelasDepara,
    normalizar_cod_tributacao,
    resolver_codigo_servico,
    resolver_natureza_despesa,
    resolver_natureza_rendimento,
)
from agent.domain.classificacao_nf.layout import motivo_recusa_layout_ou_tipo
from agent.domain.classificacao_nf.modelos import NotaErp, NotaPdf, PreparacaoClassificacao
from agent.domain.classificacao_nf.status import MOTIVOS, StatusNf
from agent.domain.classificacao_nf.validacao import validar_cabecalho
from agent.domain.classificacao_nf.vencimento import calcular_vencimento


def _codigo_retencao_lynn(irrf: str | None, pcc: str | None) -> str | None:
    partes: list[str] = []
    for valor in (irrf, pcc):
        if valor and valor.strip() and valor.strip() != "-":
            partes.append(valor.strip())
    return ",".join(partes) if partes else None


def _preparar_via_lynn(
    erp: NotaErp,
    pdf: NotaPdf,
    tabelas: TabelasDepara,
    *,
    referencia: date,
) -> PreparacaoClassificacao | None:
    """Usa bloco classificacao do agente. None = cair no depara local (legado)."""
    clf = pdf.classificacao
    if clf is None or not clf.status:
        return None

    if clf.nao_classificado:
        return PreparacaoClassificacao(
            ok=False,
            status=StatusNf.NAO_CLASSIFICADO,
            motivo=clf.motivo or MOTIVOS.campo_nao_coletado("classificação LYNN"),
            codigo_servico=clf.cod_tributacao or (pdf.codigo_servico or None),
            natureza_despesa=clf.natureza_despesa,
            natureza_rendimento=clf.natureza_rendimento,
            codigo_retencao=_codigo_retencao_lynn(
                clf.cod_retencao_irrf, clf.cod_retencao_pcc
            ),
            nota_erp=erp,
            nota_pdf=pdf,
        )

    recusa = motivo_recusa_layout_ou_tipo(clf)
    if recusa:
        return PreparacaoClassificacao(
            ok=False,
            status=StatusNf.NAO_CLASSIFICADO,
            motivo=recusa,
            codigo_servico=clf.cod_tributacao or (pdf.codigo_servico or None),
            natureza_despesa=clf.natureza_despesa,
            natureza_rendimento=clf.natureza_rendimento,
            codigo_retencao=_codigo_retencao_lynn(
                clf.cod_retencao_irrf, clf.cod_retencao_pcc
            ),
            nota_erp=erp,
            nota_pdf=pdf,
        )

    if not clf.validacao_ok:
        # Status inesperado: não forçar; deixa fallback depara.
        return None

    codigo_bruto = (clf.cod_tributacao or pdf.codigo_servico or "").strip()
    codigo = normalizar_cod_tributacao(codigo_bruto, tabelas.natureza_rendimento)
    if not codigo:
        return PreparacaoClassificacao(
            ok=False,
            status=StatusNf.NAO_CLASSIFICADO,
            motivo=MOTIVOS.DEPARA_RENDIMENTO_AUSENTE,
            codigo_servico=codigo_bruto or None,
            natureza_despesa=clf.natureza_despesa,
            natureza_rendimento=clf.natureza_rendimento,
            codigo_retencao=_codigo_retencao_lynn(
                clf.cod_retencao_irrf, clf.cod_retencao_pcc
            ),
            nota_erp=erp,
            nota_pdf=pdf,
        )
    vencimento = calcular_vencimento(
        nivel=erp.nivel,
        codigo_fornecedor=erp.codigo_fornecedor,
        referencia=referencia,
        tabela_especial=tabelas.vencimento_especial,
    )
    return PreparacaoClassificacao(
        ok=True,
        status=StatusNf.PRONTO_UI,
        motivo=None,
        codigo_servico=codigo,
        natureza_despesa=clf.natureza_despesa,
        natureza_rendimento=clf.natureza_rendimento,
        codigo_retencao=_codigo_retencao_lynn(
            clf.cod_retencao_irrf, clf.cod_retencao_pcc
        ),
        data_vencimento=vencimento,
        nota_erp=erp,
        nota_pdf=pdf,
    )


def preparar_classificacao(
    erp: NotaErp,
    pdf: NotaPdf,
    tabelas: TabelasDepara,
    *,
    referencia: date | None = None,
) -> PreparacaoClassificacao:
    """Aplica regras de domínio. Não abre UI nem chama APIs.

    Ordem: validação ERP×PDF (RN-04) → classificação LYNN (se houver) →
    filtro de layout/tipo (F6) → deparas locais (fallback) → vencimento (RN-08).
    """
    ref = referencia or date.today()

    validacao = validar_cabecalho(erp, pdf)
    if not validacao.ok:
        return PreparacaoClassificacao(
            ok=False,
            status=StatusNf.NAO_CLASSIFICADO,
            motivo=validacao.motivo,
            nota_erp=erp,
            nota_pdf=pdf,
        )

    via_lynn = _preparar_via_lynn(erp, pdf, tabelas, referencia=ref)
    if via_lynn is not None:
        return via_lynn

    codigo = resolver_codigo_servico(pdf.codigo_servico, tabelas.codigo_servico)
    if codigo is None:
        return PreparacaoClassificacao(
            ok=False,
            status=StatusNf.NAO_CLASSIFICADO,
            motivo=MOTIVOS.DEPARA_SERVICO_AUSENTE,
            nota_erp=erp,
            nota_pdf=pdf,
        )

    impostos = pdf.impostos
    natureza = resolver_natureza_despesa(
        codigo,
        tem_iss_a_recolher=impostos.tem_iss_a_recolher,
        tem_irrf=impostos.tem_irrf,
        tem_pcc=impostos.tem_pcc,
        tabela=tabelas.natureza_despesa,
    )
    if natureza is None:
        return PreparacaoClassificacao(
            ok=False,
            status=StatusNf.NAO_CLASSIFICADO,
            motivo=MOTIVOS.DEPARA_NATUREZA_AUSENTE,
            codigo_servico=codigo,
            nota_erp=erp,
            nota_pdf=pdf,
        )

    natureza_rendimento: str | None = None
    if impostos.tem_retencao:
        natureza_rendimento = resolver_natureza_rendimento(
            codigo, tabelas.natureza_rendimento
        )
        if natureza_rendimento is None:
            return PreparacaoClassificacao(
                ok=False,
                status=StatusNf.NAO_CLASSIFICADO,
                motivo=MOTIVOS.DEPARA_RENDIMENTO_AUSENTE,
                codigo_servico=codigo,
                natureza_despesa=natureza.natureza_despesa,
                codigo_retencao=natureza.codigo_retencao,
                nota_erp=erp,
                nota_pdf=pdf,
            )

    vencimento = calcular_vencimento(
        nivel=erp.nivel,
        codigo_fornecedor=erp.codigo_fornecedor,
        referencia=ref,
        tabela_especial=tabelas.vencimento_especial,
    )

    return PreparacaoClassificacao(
        ok=True,
        status=StatusNf.PRONTO_UI,
        motivo=None,
        codigo_servico=codigo,
        natureza_despesa=natureza.natureza_despesa,
        natureza_rendimento=natureza_rendimento,
        codigo_retencao=natureza.codigo_retencao,
        data_vencimento=vencimento,
        nota_erp=erp,
        nota_pdf=pdf,
    )
