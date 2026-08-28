"""Checkpoint JSON por NF — permite retomar lote sem reprocessar o que já fechou."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def chave_nf(
    *,
    filial_codigo: str,
    numero_nf: str,
    codigo_fornecedor: str,
) -> str:
    return f"{filial_codigo}|{numero_nf}|{codigo_fornecedor}"


@dataclass
class ItemCheckpoint:
    chave: str
    filial_codigo: str
    numero_nf: str
    codigo_fornecedor: str = ""
    codigo_loja: str = ""
    nome_fornecedor: str = ""
    filial_nome: str = ""
    cod_objeto: str = ""
    ac9_codent: str = ""
    nivel: int = 0
    tipo_nf: str = ""
    serie_nf: str = ""
    data_emissao_nf: str = ""
    data_entrada_nf: str = ""
    valor_total_nf: str = ""
    status: str = ""
    motivo: str | None = None
    codigo_servico: str | None = None
    natureza_despesa: str | None = None
    natureza_rendimento: str | None = None
    codigo_retencao: str | None = None
    data_vencimento: str | None = None
    pdf_path: str | None = None
    # Impostos (valores) para regras de UI MATA103
    issqn: str = "0"
    irrf: str = "0"
    pis: str = "0"
    cofins: str = "0"
    csll: str = "0"
    atualizado_em: str = ""

    @property
    def tem_iss_a_recolher(self) -> bool:
        from decimal import Decimal

        try:
            return Decimal(self.issqn or "0") > 0
        except Exception:
            return False

    @property
    def tem_irrf(self) -> bool:
        from decimal import Decimal

        try:
            return Decimal(self.irrf or "0") > 0
        except Exception:
            return False

    @property
    def tem_pcc(self) -> bool:
        from decimal import Decimal

        try:
            return (
                Decimal(self.pis or "0") > 0
                or Decimal(self.cofins or "0") > 0
                or Decimal(self.csll or "0") > 0
            )
        except Exception:
            return False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, dados: dict[str, Any]) -> ItemCheckpoint:
        conhecidos = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in dados.items() if k in conhecidos})


@dataclass
class Checkpoint:
    caminho: Path
    corrida_id: str = ""
    itens: dict[str, ItemCheckpoint] = field(default_factory=dict)

    @classmethod
    def carregar(cls, caminho: str | Path, *, corrida_id: str = "") -> Checkpoint:
        path = Path(caminho)
        ck = cls(caminho=path, corrida_id=corrida_id)
        if not path.is_file():
            return ck
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[Checkpoint] falha ao ler %s: %s — iniciando vazio", path, e)
            return ck
        ck.corrida_id = str(raw.get("corrida_id") or corrida_id)
        for item in raw.get("itens") or []:
            if not isinstance(item, dict):
                continue
            obj = ItemCheckpoint.from_dict(item)
            if obj.chave:
                ck.itens[obj.chave] = obj
        return ck

    def salvar(self) -> Path:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "corrida_id": self.corrida_id,
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
            "itens": [i.to_dict() for i in self.itens.values()],
        }
        tmp = self.caminho.with_suffix(self.caminho.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.caminho)
        return self.caminho

    def obter(self, chave: str) -> ItemCheckpoint | None:
        return self.itens.get(chave)

    def upsert(self, item: ItemCheckpoint) -> None:
        item.atualizado_em = datetime.now(timezone.utc).isoformat()
        self.itens[item.chave] = item

    def fila_ui(self) -> list[ItemCheckpoint]:
        from agent.domain.classificacao_nf.status import StatusNf

        return [i for i in self.itens.values() if i.status == StatusNf.PRONTO_UI]

    def resumo(self) -> dict[str, int]:
        from agent.domain.classificacao_nf.status import StatusNf

        cont: dict[str, int] = {
            StatusNf.PRONTO_UI: 0,
            StatusNf.NAO_CLASSIFICADO: 0,
            StatusNf.CLASSIFICADO: 0,
            "outros": 0,
        }
        for item in self.itens.values():
            if item.status in cont:
                cont[item.status] += 1
            else:
                cont["outros"] += 1
        cont["total"] = len(self.itens)
        return cont
