"""Status e motivos canónicos do relatório de execução."""

from __future__ import annotations


class StatusNf:
    CLASSIFICADO = "Classificado"
    NAO_CLASSIFICADO = "Não Classificado"
    # Data-plane OK; status final Classificado só após MATA103 + confirmação.
    PRONTO_UI = "Pronto para classificar"


class MOTIVOS:
    """Textos estáveis para a coluna MOTIVO (CR FSB)."""

    NUMERO_DIVERGENTE = "Número da nota fiscal divergente"
    PRESTADOR_DIVERGENTE = "Prestador divergente"
    TOMADOR_DIVERGENTE = "Tomador divergente"
    DATA_EMISSAO_DIVERGENTE = "Data de emissão divergente"
    VALOR_DIVERGENTE = "Valor total divergente"
    TIPO_DIVERGENTE = "Tipo de nota fiscal divergente"
    NF_NAO_ENCONTRADA_ERP = "Nota fiscal não foi encontrada pelo ERP"
    FILTRO_MATA103_NAO_CARREGADO = "Tela filtro MATA103 não foi devidamente carregada"
    DEPARA_NATUREZA_AUSENTE = "Interno - Natureza de despesa não encontrada no depara"
    DEPARA_SERVICO_AUSENTE = "Interno - Código de serviço não encontrado no depara"
    DEPARA_RENDIMENTO_AUSENTE = "Interno - Natureza de rendimento não encontrada no depara"
    CAMPO_NAO_COLETADO_PREFIXO = "Interno - Campo {campo} não coletado"
    LAYOUT_NAO_SUPORTADO = "Layout da NFS-e não suportado"

    @classmethod
    def campo_nao_coletado(cls, campo: str) -> str:
        return cls.CAMPO_NAO_COLETADO_PREFIXO.format(campo=campo)
