"""Cliente HTTP LYNN/DTA (dois contratos).

Homologação (Flows / workflow):

  POST {base}/api/flows/workflow/{workflow_id}/run
  Headers: x-dta-api-key, x-dta-project, Accept

Agente LYNN (Agents — produção FSB, depois):

  GET/POST {base}/api/agents/projects/{project}/agents/{agent_id}/run
  Headers: Authorization Bearer, x-dta-project, x-dta-session-id

Anexo PDF em ``dta_extras.dta_files`` (data-URL).
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx

from agent.domain.classificacao_nf.modelos import NotaPdf
from agent.integrations.lynn.mappers import nota_pdf_de_dict

logger = logging.getLogger(__name__)

RunMode = Literal["workflow", "agent"]
AuthMode = Literal["api_key", "bearer"]


def _authorization(token: str) -> str | None:
    raw = (token or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("bearer "):
        return raw
    return f"Bearer {raw}"


def _data_url(path: Path) -> tuple[str, str, str]:
    mime = mimetypes.guess_type(path.name)[0] or "application/pdf"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return path.name, mime, f"data:{mime};base64,{b64}"


def _json_de_texto(texto: str) -> dict[str, Any] | None:
    """Parse JSON puro ou bloco markdown `` ```json ... ``` ``."""
    import json
    import re

    raw = (texto or "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if m:
        try:
            parsed = json.loads(m.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    # fallback: primeiro objeto JSON no texto
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _desembrulhar_lynn(payload: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Extrai (extracao, classificacao) da resposta DTA/agente."""
    if not isinstance(payload, dict):
        raise ValueError("resposta LYNN: esperado objeto JSON")

    def _from_obj(obj: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        clf = obj.get("classificacao") if isinstance(obj.get("classificacao"), dict) else None
        if isinstance(obj.get("extracao"), dict):
            return obj["extracao"], clf
        # Schema já plano / só extracao
        if any(
            k in obj
            for k in ("numero_nf", "x_numero_nfs", "x_numero", "nfse_info", "x_prestador")
        ):
            return obj, clf
        return obj, clf

    if any(
        k in payload
        for k in ("extracao", "numero_nf", "x_numero_nfs", "x_numero", "nfse_info")
    ):
        return _from_obj(payload)

    content = payload.get("content")
    if isinstance(content, dict):
        return _from_obj(content)
    if isinstance(content, str):
        parsed = _json_de_texto(content)
        if parsed is not None:
            return _from_obj(parsed)

    data = payload.get("data")
    if isinstance(data, dict):
        try:
            msg = (
                data.get("llm_response", {})
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content")
            )
            if isinstance(msg, dict):
                return _from_obj(msg)
            if isinstance(msg, str):
                parsed = _json_de_texto(msg)
                if parsed is not None:
                    return _from_obj(parsed)
        except Exception:
            pass
        if any(
            k in data
            for k in ("extracao", "numero_nf", "x_numero_nfs", "x_numero", "nfse_info")
        ):
            return _from_obj(data)
    return payload, None


def _payload_para_nota(payload: Any) -> dict[str, Any]:
    """Compat: devolve só o bloco de extração (testes/legado)."""
    extracao, _clf = _desembrulhar_lynn(payload)
    return extracao


def _norm_run_mode(value: str) -> RunMode:
    v = (value or "").strip().lower()
    if v in ("workflow", "flow", "flows"):
        return "workflow"
    if v in ("agent", "agents"):
        return "agent"
    raise ValueError(f"LYNN_RUN_MODE inválido: {value!r} (use workflow|agent)")


def _norm_auth_mode(value: str, *, run_mode: RunMode) -> AuthMode:
    v = (value or "").strip().lower()
    if not v:
        return "api_key" if run_mode == "workflow" else "bearer"
    if v in ("api_key", "apikey", "x-dta-api-key", "dta_api_key"):
        return "api_key"
    if v in ("bearer", "jwt", "authorization"):
        return "bearer"
    raise ValueError(f"LYNN_AUTH_MODE inválido: {value!r} (use api_key|bearer)")


class HttpLynnClient:
    """
    Cliente DTA para extração de PDF.

    ``run_mode=workflow`` — homologação Flows; ``run_mode=agent`` — Agents LYNN.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str = "",
        project: str = "",
        agent_id: str = "",
        workflow_id: str = "",
        run_mode: str = "workflow",
        auth_mode: str = "",
        timeout_s: float = 120.0,
        message: str = "Segue Documento Fiscal",
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.project = (project or "").strip()
        self.agent_id = (agent_id or "").strip()
        self.workflow_id = (workflow_id or "").strip()
        self.run_mode = _norm_run_mode(run_mode)
        self.auth_mode = _norm_auth_mode(auth_mode, run_mode=self.run_mode)
        self.timeout_s = timeout_s
        self.message = message
        self._client = client
        self._owns_client = client is None

    def _run_url(self) -> str:
        if self.run_mode == "workflow":
            if not self.workflow_id:
                raise ValueError("LYNN_WORKFLOW_ID é obrigatório no modo workflow")
            return f"{self.base_url}/api/flows/workflow/{self.workflow_id}/run"
        if not self.project or not self.agent_id:
            raise ValueError(
                "LYNN_PROJECT e LYNN_AGENT_ID são obrigatórios no modo agent"
            )
        return (
            f"{self.base_url}/api/agents/projects/{self.project}"
            f"/agents/{self.agent_id}/run"
        )

    def _auth_headers(self, *, session_id: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/json, text/plain, */*",
            "x-dta-trace-id": str(uuid.uuid4()),
        }
        raw = (self.token or "").strip()
        if self.auth_mode == "api_key":
            if raw:
                # Aceita valor já com prefixo acidental "Bearer "
                key = raw[7:].strip() if raw.lower().startswith("bearer ") else raw
                headers["x-dta-api-key"] = key
        else:
            auth = _authorization(raw)
            if auth:
                headers["Authorization"] = auth
        if self.project:
            headers["x-dta-project"] = self.project
        if session_id and self.run_mode == "agent":
            headers["x-dta-session-id"] = session_id
        return headers

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_s)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def extrair_nf(self, pdf_path: str | Path) -> NotaPdf:
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"PDF não encontrado: {path}")
        if not (self.token or "").strip():
            label = "LYNN_API_KEY" if self.auth_mode == "api_key" else "LYNN_API_TOKEN"
            raise ValueError(f"{label} ausente ({self.auth_mode})")
        if self.run_mode == "workflow" and not self.project:
            raise ValueError("LYNN_PROJECT é obrigatório (header x-dta-project)")

        run_url = self._run_url()
        filename, mime, data_url = _data_url(path)
        http = self._http()

        session_id: str | None = None
        # Init de sessão só no contrato Agents (CNAB/UI); workflow = POST direto.
        if self.run_mode == "agent":
            session_id = str(uuid.uuid4())
            try:
                init = http.get(run_url, headers=self._auth_headers())
                sid = init.headers.get("x-dta-session-id")
                if sid:
                    session_id = sid
                if init.status_code < 400 and init.content:
                    try:
                        body = init.json()
                    except Exception:
                        body = None
                    if isinstance(body, dict):
                        for k in ("session_id", "sessionId", "id"):
                            if body.get(k):
                                session_id = str(body[k])
                                break
            except Exception as e:
                logger.warning("[Lynn] GET init opcional falhou: %s", e)

        payload = {
            "content": self.message,
            "data": {},
            "dta_extras": {
                "dta_files": [
                    {
                        "filename": filename,
                        "mimetype": mime,
                        "data": data_url,
                    }
                ]
            },
        }
        resp = http.post(
            run_url,
            headers={
                **self._auth_headers(session_id=session_id),
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        raw = resp.json()
        extracao, classificacao = _desembrulhar_lynn(raw)
        nota = nota_pdf_de_dict(extracao, classificacao=classificacao)
        nota.extras["_resposta_lynn"] = raw
        logger.info(
            "[Lynn] DTA %s run ok pdf=%s numero=%s status=%s",
            self.run_mode,
            path.name,
            nota.numero_nf,
            resp.status_code,
        )
        return nota
