"""Cliente Protheus API — lista NFs TES 002 e confirma status Classificada."""

from __future__ import annotations

from agent.integrations.protheus_api.client import (
    ProtheusApiClient,
    criar_protheus_api_client,
)
from agent.integrations.protheus_api.fake import FakeProtheusApiClient
from agent.integrations.protheus_api.generic_query import GenericQueryProtheusApiClient
from agent.integrations.protheus_api.http_client import HttpProtheusApiClient

__all__ = [
    "FakeProtheusApiClient",
    "GenericQueryProtheusApiClient",
    "HttpProtheusApiClient",
    "ProtheusApiClient",
    "criar_protheus_api_client",
]
