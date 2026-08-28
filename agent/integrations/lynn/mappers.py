"""Mapeamento JSON LYNN → NotaPdf (schema provisório)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

from agent.domain.classificacao_nf.modelos import ClassificacaoLynn, ImpostosNf, NotaPdf


def _get(dados: Mapping[str, Any], *chaves: str, default: Any = "") -> Any:
    for chave in chaves:
        if chave in dados and dados[chave] is not None:
            return dados[chave]
        lower = chave.casefold()
        for k, v in dados.items():
            if str(k).casefold() == lower and v is not None:
                return v
    return default


def _data(valor: Any) -> date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    texto = str(valor).strip().split()[0]  # "dd/mm/aaaa HH:MM:SS" → data
    if "/" in texto:
        dia, mes, ano = texto.split("/", 2)
        return date(int(ano), int(mes), int(dia))
    return date.fromisoformat(texto[:10])


def _decimal(valor: Any) -> Decimal:
    if valor is None or valor == "":
        return Decimal("0")
    texto = str(valor).strip()
    if not texto or texto.casefold() in {
        "não informado",
        "nao informado",
        "n/a",
        "-",
    }:
        return Decimal("0")
    # BR: 4.000,00 → 4000.00 | 10,5 → 10.5
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", ".")
    return Decimal(texto)


def _cnpj_digitos(valor: Any) -> str:
    texto = str(valor or "").strip()
    digitos = "".join(ch for ch in texto if ch.isdigit())
    return digitos or texto


def _achatar_lynn(dados: Mapping[str, Any]) -> dict[str, Any]:
    """Aceita schema plano, `nfse_info` / `x_*` V.3 ou blocos homolog (x_prestador…)."""
    flat: dict[str, Any] = dict(dados)
    nested = dados.get("nfse_info") or dados.get("nfs_info") or dados.get("data")
    if isinstance(nested, Mapping):
        flat = {**dict(nested), **flat}

    def _merge_bloco(bloco: Any, mapeamento: dict[str, str]) -> None:
        if not isinstance(bloco, Mapping):
            return
        for origem, destino in mapeamento.items():
            if flat.get(destino) not in (None, ""):
                continue
            if origem in bloco and bloco[origem] not in (None, ""):
                flat[destino] = bloco[origem]

    _merge_bloco(
        dados.get("x_prestador"),
        {"x_cnpj": "cnpj_prestador", "x_cnpj_prestador": "cnpj_prestador"},
    )
    _merge_bloco(
        dados.get("x_tomador"),
        {"x_cnpj": "cnpj_tomador", "x_cnpj_tomador": "cnpj_tomador"},
    )
    _merge_bloco(
        dados.get("x_servico"),
        {
            "x_codigo_nacional": "codigo_servico",
            "x_cod_tributacao": "codigo_servico",
            "x_cod_servico": "codigo_servico",
        },
    )
    _merge_bloco(
        dados.get("x_financeiro"),
        {
            "x_valor_servico": "valor_total",
            "x_valor_liquido": "valor_total",
            "x_valor_total_nfs": "valor_total",
        },
    )
    _merge_bloco(
        dados.get("x_impostos") or dados.get("x_impostos_valores"),
        {
            "x_cod_servico": "codigo_servico",
            "x_valor_total_nota": "valor_total",
            "x_issqn": "issqn",
            "x_irrf": "irrf",
            "x_pis": "pis",
            "x_cofins": "cofins",
            "x_csll": "csll",
            "x_valor_issqn": "issqn",
            "x_valor_irrf": "irrf",
            "x_valor_pis": "pis",
            "x_valor_cofins": "cofins",
            "x_valor_csll": "csll",
            "x_data_emissao": "data_emissao",
            "x_tipo_de_nota": "tipo_nf",
        },
    )

    # Prompt Extrator PDF V.3 → chaves canónicas do domínio
    alias = {
        "x_numero": "numero_nf",
        "x_numero_nfs": "numero_nf",
        "x_cnpj_prestador": "cnpj_prestador",
        "x_cnpj_tomador": "cnpj_tomador",
        "x_cod_tributacao": "codigo_servico",
        "x_codigo_servico": "codigo_servico",
        "x_cod_servico": "codigo_servico",
        "x_valor_total_nfs": "valor_total",
        "x_valor_total": "valor_total",
        "x_valor_liquido": "valor_total",
        "x_data_emissao": "data_emissao",
        "x_valor_issqn": "issqn",
        "x_valor_irrf": "irrf",
        "x_valor_pis": "pis",
        "x_valor_cofins": "cofins",
        "x_valor_csll": "csll",
    }
    for origem, destino in alias.items():
        if destino not in flat or flat.get(destino) in (None, ""):
            if origem in flat and flat[origem] is not None:
                flat[destino] = flat[origem]
    if flat.get("cnpj_prestador"):
        flat["cnpj_prestador"] = _cnpj_digitos(flat["cnpj_prestador"])
    if flat.get("cnpj_tomador"):
        flat["cnpj_tomador"] = _cnpj_digitos(flat["cnpj_tomador"])
    tipo = str(flat.get("tipo_nf") or "")
    if flat.get("x_nfse") is True and not tipo:
        flat["tipo_nf"] = "NFS"
    elif "serviço" in tipo.casefold() or "servico" in tipo.casefold():
        flat["tipo_nf"] = "NFS"
    _corrigir_numero_nfs_confundido_com_dps(flat)
    return flat


def _so_digitos(valor: Any) -> str:
    return "".join(ch for ch in str(valor or "") if ch.isdigit())


def _norm_num_nf(valor: Any) -> str:
    dig = _so_digitos(valor)
    if not dig:
        return ""
    return str(int(dig))


def _corrigir_numero_nfs_confundido_com_dps(flat: dict[str, Any]) -> None:
    """SP/DANFSe: agente às vezes copia x_dps_numero em x_numero_nfs.

    Se numero == DPS (ou vazio com DPS) e houver chave de acesso, deriva o
    número da NFS-e do sufixo significativo da chave (ex.: …09951475).
    """
    dps = str(flat.get("x_dps_numero") or flat.get("dps_numero") or "").strip()
    numero = str(
        flat.get("numero_nf") or flat.get("x_numero_nfs") or flat.get("x_numero") or ""
    ).strip()
    chave = str(flat.get("x_chave_acesso") or flat.get("chave_acesso") or "")
    digitos = _so_digitos(chave)
    if len(digitos) < 20:
        return
    dps_n = _norm_num_nf(dps)
    num_n = _norm_num_nf(numero)
    if num_n and dps_n and num_n != dps_n:
        return
    if not dps_n and num_n:
        return
    dps_dig = _so_digitos(dps)
    for width in range(9, 5, -1):
        if len(digitos) < width:
            continue
        cand = digitos[-width:]
        # Chave costuma concatenar DPS + nNF (ex.: 1 + 09951475 → 109951475).
        if dps_dig and cand.startswith(dps_dig) and len(cand) > len(dps_dig):
            rest = cand[len(dps_dig) :]
            if _norm_num_nf(rest) and _norm_num_nf(rest) != dps_n:
                cand = rest
        cand_n = _norm_num_nf(cand)
        if not cand_n or cand_n == dps_n:
            continue
        if not (4 <= len(cand_n) <= 9):
            continue
        flat["numero_nf"] = cand
        flat["x_numero_nfs"] = cand
        return


def _aplicar_mei_e_fallback_classificacao(
    clf: ClassificacaoLynn | None,
    dados_flat: Mapping[str, Any],
) -> ClassificacaoLynn | None:
    """Espelha x_mei e aplica regra MEI quando o agente parou em V5 (rendimento)."""
    if clf is None:
        return None
    mei_ext = _boolish(_get(dados_flat, "x_mei", "mei", default=False))
    if not mei_ext:
        prest = dados_flat.get("x_prestador")
        if isinstance(prest, Mapping):
            mei_ext = _boolish(prest.get("x_mei") or prest.get("mei"))
    mei_ext = bool(mei_ext or clf.mei)
    motivo = (clf.motivo or "").casefold()
    parou_rendimento = (
        clf.nao_classificado
        and "natureza de rendimento" in motivo
    )
    if mei_ext and parou_rendimento:
        return ClassificacaoLynn(
            status="ValidacaoOk",
            motivo=None,
            tipo_nf_pdf=True if clf.tipo_nf_pdf is None else clf.tipo_nf_pdf,
            layout=clf.layout,
            cod_tributacao=clf.cod_tributacao
            or _texto_ou_none(_get(dados_flat, "codigo_servico", "x_cod_servico")),
            mei=True,
            issqn_retido=clf.issqn_retido,
            natureza_rendimento=None,
            natureza_despesa=clf.natureza_despesa or "5000000022",
            cod_retencao_irrf=clf.cod_retencao_irrf or "-",
            cod_retencao_pcc=clf.cod_retencao_pcc or "-",
        )
    if mei_ext and not clf.mei:
        return ClassificacaoLynn(
            status=clf.status,
            motivo=clf.motivo,
            tipo_nf_pdf=clf.tipo_nf_pdf,
            layout=clf.layout,
            cod_tributacao=clf.cod_tributacao,
            mei=True,
            issqn_retido=clf.issqn_retido,
            natureza_rendimento=clf.natureza_rendimento,
            natureza_despesa=clf.natureza_despesa,
            cod_retencao_irrf=clf.cod_retencao_irrf,
            cod_retencao_pcc=clf.cod_retencao_pcc,
        )
    return clf


def _data_lynn(valor: Any) -> date | None:
    """ISO, dd/mm/aaaa ou ddmmyyyy (prompt LYNN V.3)."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    texto = str(valor).strip()
    if len(texto) == 8 and texto.isdigit():
        return date(int(texto[4:8]), int(texto[2:4]), int(texto[0:2]))
    return _data(valor)


def _boolish(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return False
    return str(valor).strip().casefold() in {"true", "1", "sim", "yes", "s"}


def _texto_ou_none(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto or texto.casefold() in {"null", "none", "-"}:
        return None
    return texto


def classificacao_lynn_de_dict(dados: Mapping[str, Any] | None) -> ClassificacaoLynn | None:
    if not isinstance(dados, Mapping) or not dados:
        return None
    return ClassificacaoLynn(
        status=_texto_ou_none(_get(dados, "STATUS", "status")),
        motivo=_texto_ou_none(_get(dados, "MOTIVO", "motivo")),
        tipo_nf_pdf=_boolish(_get(dados, "TIPO_NF_PDF", "tipo_nf_pdf", default=False)),
        layout=_texto_ou_none(_get(dados, "LAYOUT", "layout")),
        cod_tributacao=_texto_ou_none(
            _get(dados, "COD_TRIBUTACAO", "cod_tributacao", "codigo_servico")
        ),
        mei=_boolish(_get(dados, "MEI", "mei", default=False)),
        issqn_retido=_boolish(_get(dados, "ISSQN_RETIDO", "issqn_retido", default=False)),
        natureza_rendimento=_texto_ou_none(
            _get(dados, "NATUREZA_RENDIMENTO", "natureza_rendimento")
        ),
        natureza_despesa=_texto_ou_none(
            _get(dados, "NATUREZA_DESPESA", "natureza_despesa")
        ),
        cod_retencao_irrf=_texto_ou_none(
            _get(dados, "COD_RETENCAO_IRRF", "cod_retencao_irrf")
        ),
        cod_retencao_pcc=_texto_ou_none(
            _get(dados, "COD_RETENCAO_PCC", "cod_retencao_pcc")
        ),
    )


def nota_pdf_de_dict(
    dados: Mapping[str, Any],
    *,
    classificacao: Mapping[str, Any] | ClassificacaoLynn | None = None,
) -> NotaPdf:
    clf: ClassificacaoLynn | None
    if isinstance(classificacao, ClassificacaoLynn):
        clf = classificacao
    elif isinstance(classificacao, Mapping):
        clf = classificacao_lynn_de_dict(classificacao)
    else:
        clf = classificacao_lynn_de_dict(
            dados.get("classificacao") if isinstance(dados.get("classificacao"), Mapping) else None
        )

    # Extracao pode vir aninhada ou já plana
    extracao = dados.get("extracao") if isinstance(dados.get("extracao"), Mapping) else dados
    flat_src = extracao if isinstance(extracao, Mapping) else dados
    dados_flat = _achatar_lynn(flat_src)
    clf = _aplicar_mei_e_fallback_classificacao(clf, dados_flat)
    impostos_raw = _get(dados_flat, "impostos", default={}) or {}
    if not isinstance(impostos_raw, Mapping):
        impostos_raw = {}
    impostos = ImpostosNf(
        issqn=_decimal(
            _get(impostos_raw, "issqn", "ISSQN", "iss", default=None)
            or _get(dados_flat, "issqn", "x_valor_issqn", default="0")
        ),
        irrf=_decimal(
            _get(impostos_raw, "irrf", "IRRF", "ir", default=None)
            or _get(dados_flat, "irrf", "x_valor_irrf", default="0")
        ),
        pis=_decimal(
            _get(impostos_raw, "pis", "PIS", default=None)
            or _get(dados_flat, "pis", "x_valor_pis", default="0")
        ),
        cofins=_decimal(
            _get(impostos_raw, "cofins", "COFINS", default=None)
            or _get(dados_flat, "cofins", "x_valor_cofins", default="0")
        ),
        csll=_decimal(
            _get(impostos_raw, "csll", "CSLL", "contribuicoes_sociais", default=None)
            or _get(dados_flat, "csll", "x_valor_csll", default="0")
        ),
    )
    ausente = _get(dados_flat, "campo_ausente", "campo_faltante", default=None) or None
    if ausente is not None:
        ausente = str(ausente)
    codigo = str(
        _get(
            dados_flat,
            "codigo_servico",
            "COD_SERVICO",
            "x_cod_tributacao",
            "x_cod_servico",
        )
    )
    if clf and clf.cod_tributacao and not (codigo or "").strip():
        codigo = clf.cod_tributacao
    tipo = str(_get(dados_flat, "tipo_nf", "TIPO_NF", "tipo") or "")
    if not tipo and clf and clf.tipo_nf_pdf:
        tipo = "NFS"
    if not tipo:
        tipo = "NFS"
    extras = dict(dados_flat)
    if clf is not None:
        extras["classificacao"] = {
            "STATUS": clf.status,
            "MOTIVO": clf.motivo,
            "NATUREZA_DESPESA": clf.natureza_despesa,
            "NATUREZA_RENDIMENTO": clf.natureza_rendimento,
            "COD_TRIBUTACAO": clf.cod_tributacao,
            "COD_RETENCAO_IRRF": clf.cod_retencao_irrf,
            "COD_RETENCAO_PCC": clf.cod_retencao_pcc,
            "LAYOUT": clf.layout,
            "MEI": clf.mei,
        }
    return NotaPdf(
        numero_nf=str(
            _get(dados_flat, "numero_nf", "numero", "NUMERO_NF", "x_numero_nfs", "x_numero")
        ),
        cnpj_prestador=str(
            _get(
                dados_flat,
                "cnpj_prestador",
                "cnpj_emitente",
                "CNPJ_PRESTADOR",
                "x_cnpj_prestador",
            )
        ),
        cnpj_tomador=str(
            _get(dados_flat, "cnpj_tomador", "CNPJ_TOMADOR", "x_cnpj_tomador")
        ),
        codigo_servico=codigo,
        impostos=impostos,
        valor_total=_decimal(
            _get(
                dados_flat, "valor_total", "VALOR_TOTAL", "x_valor_total_nfs", default="0"
            )
        ),
        tipo_nf=tipo,
        data_emissao=_data_lynn(
            _get(dados_flat, "data_emissao", "DATA_EMISSAO", "x_data_emissao", default=None)
        ),
        campo_ausente=ausente,
        classificacao=clf,
        extras=extras,
    )
