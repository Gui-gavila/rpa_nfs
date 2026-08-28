"""Fixtures de lab para data-plane (fila_ui > 0 sem contrato FSB).

Ativado por CLASSIFICAR_NF_LAB_SEED=1 quando API e LYNN estao em fake.
PDF pode ser fake (em memoria) ou local (fixtures/pdf_share — simula base
de conhecimento Protheus por COD_OBJETO).

Nao substitui contratos TEZK42-CONTRATO-*; apenas desbloqueia exercicio local.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from agent.domain.classificacao_nf.deparas import TabelasDepara
from agent.domain.classificacao_nf.modelos import ImpostosNf, NotaErp, NotaPdf
from agent.integrations.fileshare.fake import FakeFileshareClient
from agent.integrations.fileshare.local import LocalFileshareClient
from agent.integrations.lynn.fake import FakeLynnClient
from agent.integrations.protheus_api.fake import FakeProtheusApiClient

# Codigo de objeto / chave estaveis para correlacionar PDF e checkpoint.
# Alinhado ao campo "CODIGO DO OBJETO DO PDF" do relatorio da procedure (CR).
LAB_COD_OBJETO = "LAB-OBJ-001"
LAB_FILIAL = "0101"
LAB_NUMERO_NF = "9001"
LAB_FORNECEDOR = "F001"


def caminho_fixture_pdf_share() -> Path:
    """Raiz tipica: `{repo}/fixtures/pdf_share`."""
    return Path(__file__).resolve().parents[3] / "fixtures" / "pdf_share"


def nota_erp_lab() -> NotaErp:
    """Simula uma linha do relatorio da procedure TES 002 (incl. COD_OBJETO)."""
    return NotaErp(
        filial_codigo=LAB_FILIAL,
        filial_cnpj="12345678000199",
        codigo_fornecedor=LAB_FORNECEDOR,
        codigo_loja="01",
        cnpj_fornecedor="98765432000111",
        numero_nf=LAB_NUMERO_NF,
        serie_nf="GOV",
        data_emissao=date(2026, 6, 10),
        valor_total=Decimal("1000.00"),
        nivel=1,
        tipo_nf="NFS",
        cod_objeto=LAB_COD_OBJETO,
    )


def nota_pdf_lab() -> NotaPdf:
    return NotaPdf(
        numero_nf=LAB_NUMERO_NF,
        cnpj_prestador="98765432000111",
        cnpj_tomador="12345678000199",
        codigo_servico="1.01",
        impostos=ImpostosNf(),
        valor_total=Decimal("1000.00"),
        tipo_nf="NFS",
        data_emissao=date(2026, 6, 10),
    )


def tabelas_depara_lab() -> TabelasDepara:
    return TabelasDepara(
        codigo_servico=[{"codigo_antigo": "1.01", "codigo_novo": "1.01"}],
        natureza_despesa=[
            {
                "codigo_servico": "1.01",
                "iss_a_recolher": "0",
                "irrf": "0",
                "pcc": "0",
                "natureza_despesa": "NAT001",
            }
        ],
    )


def pdf_bytes_lab() -> bytes:
    # Cabecalho minimo; FakeLynn nao interpreta o conteudo.
    return b"%PDF-1.4 lab-seed tezk42\n%%EOF\n"


def modos_fake_ativos(
    *,
    protheus_mode: str,
    lynn_mode: str,
    pdf_mode: str,
) -> bool:
    """True se API+LYNN fake e PDF fake ou local (lab hibrido SHARE)."""
    api_ok = protheus_mode.strip().lower() == "fake"
    lynn_ok = lynn_mode.strip().lower() == "fake"
    pdf = pdf_mode.strip().lower()
    pdf_ok = pdf in ("fake", "local")
    return api_ok and lynn_ok and pdf_ok


def clientes_e_tabelas_lab(
    *,
    pdf_mode: str | None = None,
    pdf_root: str | Path | None = None,
) -> tuple[Any, Any, Any, TabelasDepara]:
    """API + LYNN + fileshare + deparas alinhados a uma NF Pronto para classificar.

    Com `pdf_mode=local`, usa `LocalFileshareClient` (ficheiro em disco por
    COD_OBJETO) — simula coleta na base de conhecimento Protheus.
    """
    from agent import config

    modo = (pdf_mode if pdf_mode is not None else config.PDF_SHARE_MODE).strip().lower()
    raiz = pdf_root if pdf_root is not None else (config.PDF_SHARE_ROOT or "")
    raiz_path = Path(raiz) if str(raiz).strip() else caminho_fixture_pdf_share()

    erp = nota_erp_lab()
    pdf = nota_pdf_lab()
    api = FakeProtheusApiClient([erp])
    lynn = FakeLynnClient(default=pdf)

    if modo == "local":
        share: Any = LocalFileshareClient(root=raiz_path)
    else:
        share = FakeFileshareClient({LAB_COD_OBJETO: pdf_bytes_lab()})

    return api, lynn, share, tabelas_depara_lab()
