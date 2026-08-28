"""Acesso aos PDFs da base de conhecimento (share montado)."""

from __future__ import annotations

from agent.integrations.fileshare.client import FileshareClient, criar_fileshare_client
from agent.integrations.fileshare.fake import FakeFileshareClient
from agent.integrations.fileshare.local import LocalFileshareClient

__all__ = [
    "FakeFileshareClient",
    "FileshareClient",
    "LocalFileshareClient",
    "criar_fileshare_client",
]
