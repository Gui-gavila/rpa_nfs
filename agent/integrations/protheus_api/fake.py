"""Dublê em memória do Protheus API (testes / lab sem contrato)."""

from __future__ import annotations

from agent.domain.classificacao_nf.modelos import NotaErp


class FakeProtheusApiClient:
    def __init__(
        self,
        pendentes: list[NotaErp] | None = None,
        *,
        classificadas: set[tuple[str, str, str]] | None = None,
    ) -> None:
        self.pendentes = list(pendentes or [])
        self.classificadas = set(classificadas or [])
        self.objetos_pdf: dict[tuple[str, str], str] = {}
        self.chamadas_lista = 0
        self.chamadas_confirma = 0
        self.chamadas_acb_objeto = 0
        self.chamadas_status_pendente = 0

    def listar_nfs_tes002_pendentes(self, *, nivel_max: int | None = None) -> list[NotaErp]:
        self.chamadas_lista += 1
        if nivel_max is None:
            return list(self.pendentes)
        return [n for n in self.pendentes if n.nivel <= nivel_max]

    def consultar_acb_objeto(self, *, filial: str, ac9_codent: str) -> str:
        self.chamadas_acb_objeto += 1
        return (self.objetos_pdf.get((filial, ac9_codent)) or "").strip()

    def status_ainda_pendente(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
        codigo_loja: str = "01",
        serie_nf: str = "GOV",
    ) -> bool:
        self.chamadas_status_pendente += 1
        chave = (filial_codigo, numero_nf, codigo_fornecedor)
        return chave not in self.classificadas

    def confirmar_classificada(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
    ) -> bool:
        self.chamadas_confirma += 1
        chave = (filial_codigo, numero_nf, codigo_fornecedor)
        return chave in self.classificadas

    def consultar_f1_status(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
        codigo_loja: str = "01",
        serie_nf: str = "GOV",
    ) -> str | None:
        chave = (filial_codigo, numero_nf, codigo_fornecedor)
        if chave in self.classificadas:
            return "A"
        return ""

    def marcar_classificada(
        self, *, filial_codigo: str, numero_nf: str, codigo_fornecedor: str
    ) -> None:
        self.classificadas.add((filial_codigo, numero_nf, codigo_fornecedor))
