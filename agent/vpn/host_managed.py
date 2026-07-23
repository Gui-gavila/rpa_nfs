"""Backend para VPN_MODE=host — o túnel é estabelecido fora deste processo.

Lab Tezk42: o operador (ou o SO) conecta o cliente WireGuard e só então roda
o agente. Em `VPN_MODE=host` o agente não conecta nem desconecta — apenas
confirma que o túnel existe antes de prosseguir. `connect()` significa
"aguardar que alguém conecte", e `disconnect()` é deliberadamente no-op:
derrubar um túnel que este processo não subiu afetaria o resto da máquina.

Verificação: se não houver forma de comprovar o túnel, `is_connected()`
devolve False. Falhar fechado é intencional.
"""

from __future__ import annotations

import logging
import socket
import time
from typing import Callable

from agent.vpn.base import VPNManager

logger = logging.getLogger(__name__)

POLL_SECONDS = 5


def parse_alvo(valor: str | None, porta_padrao: int = 443) -> tuple[str, int] | None:
    """Converte 'host', 'host:porta' ou uma URL em (host, porta). None se vazio."""
    bruto = (valor or "").strip()
    if not bruto:
        return None
    if "://" in bruto:
        from urllib.parse import urlparse

        u = urlparse(bruto)
        if u.hostname:
            return (u.hostname, u.port or (443 if u.scheme == "https" else 80))
        return None
    if ":" in bruto:
        host, _, porta = bruto.rpartition(":")
        if porta.isdigit():
            return (host, int(porta))
    return (bruto, porta_padrao)


class HostManagedVPN(VPNManager):
    """VPN estabelecida fora do processo; este backend apenas verifica e espera."""

    def __init__(
        self,
        *,
        probe: Callable[[], bool] | None = None,
        alvo: tuple[str, int] | None = None,
        wait_seconds: int = 180,
        descricao: str = "cliente VPN do host",
    ) -> None:
        # `probe` reaproveita a detecção do backend nativo (ex.: `vpncli status`,
        # `ip link show tun0`) em vez de duplicar lógica por sistema operativo.
        self.probe = probe
        # `alvo` é o fallback e o critério mais honesto: se o host do ERP responde,
        # a rota da VPN está de pé — vale igual em Windows e Linux.
        self.alvo = alvo
        self.wait_seconds = wait_seconds
        self.descricao = descricao
        logger.info(
            "[HostManagedVPN] Inicializado (probe=%s alvo=%s)",
            "sim" if probe else "não",
            f"{alvo[0]}:{alvo[1]}" if alvo else "não definido",
        )

    def connect(self) -> bool:
        """Aguarda que o túnel seja estabelecido fora deste processo."""
        if self.is_connected():
            logger.info("[HostManagedVPN] Túnel já ativo")
            return True

        if not self.probe and not self.alvo:
            logger.error(
                "[HostManagedVPN] Sem probe nem alvo de verificação — não é possível "
                "confirmar a VPN. Defina VPN_PROBE_TARGET (host:porta alcançável "
                "somente pela VPN) ou use VPN_MODE=container."
            )
            return False

        logger.warning(
            "[HostManagedVPN] VPN_MODE=host: conecte pelo %s. "
            "Aguardando até %ss...",
            self.descricao,
            self.wait_seconds,
        )
        deadline = time.time() + self.wait_seconds
        while time.time() < deadline:
            if self.is_connected():
                logger.info("[HostManagedVPN] Túnel detectado — prosseguindo")
                return True
            time.sleep(POLL_SECONDS)

        logger.error("[HostManagedVPN] Túnel não detectado em %ss", self.wait_seconds)
        return False

    def disconnect(self) -> None:
        """No-op: este processo não estabeleceu o túnel, não deve derrubá-lo."""
        logger.debug("[HostManagedVPN] disconnect ignorado (túnel é do host)")

    def is_connected(self) -> bool:
        if self.probe is not None:
            try:
                if self.probe():
                    return True
            except Exception as e:
                logger.debug("[HostManagedVPN] probe falhou: %s", e)

        if self.alvo is not None:
            host, porta = self.alvo
            try:
                with socket.create_connection((host, porta), timeout=5):
                    logger.debug("[HostManagedVPN] %s:%s alcançável", host, porta)
                    return True
            except OSError as e:
                logger.debug("[HostManagedVPN] %s:%s inalcançável: %s", host, porta, e)

        if self.probe is None and self.alvo is None:
            logger.warning(
                "[HostManagedVPN] sem forma de verificar o túnel — assumindo desconectado"
            )
        return False
