"""Fábrica de VPN — WireGuard (+ HostManaged em VPN_MODE=host).

Especialização Tezk42 (FSB): único backend nativo é WireGuard.

    VPN_TYPE  WIREGUARD | WG
    VPN_MODE  host (túnel externo) | container (wg-quick no processo)

Imports de backend são tardios para não quebrar ambientes sem `wg`.
"""

from __future__ import annotations

import logging

from agent.config import (
    VPN_HOST_WAIT_SECONDS,
    VPN_PROBE_TARGET,
    VPN_TYPE,
    WIREGUARD_CONFIG,
    WIREGUARD_CONFIG_PATH,
    WIREGUARD_DNS,
    WIREGUARD_INTERFACE,
    normalize_vpn_mode,
    resolve_erp_perfil,
)
from agent.vpn.base import VPNManager

logger = logging.getLogger(__name__)

_WIREGUARD_TYPES = {"WIREGUARD", "WG"}

TIPOS_SUPORTADOS = sorted(_WIREGUARD_TYPES)


def _build_backend(vpn_type: str) -> VPNManager:
    """Instancia o backend nativo da tecnologia."""
    tipo = (vpn_type or "").strip().upper()

    if tipo in _WIREGUARD_TYPES:
        from agent.vpn.wireguard import WireGuardVPN

        logger.debug("[VPN Factory] backend=WireGuardVPN")
        return WireGuardVPN(
            config_content=WIREGUARD_CONFIG,
            config_path=WIREGUARD_CONFIG_PATH,
            interface=WIREGUARD_INTERFACE,
            dns_servers=WIREGUARD_DNS,
        )

    raise ValueError(
        f"VPN_TYPE não suportado: {vpn_type!r}. Use um de: {', '.join(TIPOS_SUPORTADOS)}"
    )


def _classe_do_tipo(vpn_type: str) -> type[VPNManager]:
    """Classe do backend, sem instanciar (preflight consulta requisitos_config)."""
    tipo = (vpn_type or "").strip().upper()

    if tipo in _WIREGUARD_TYPES:
        from agent.vpn.wireguard import WireGuardVPN

        return WireGuardVPN

    raise ValueError(
        f"VPN_TYPE não suportado: {vpn_type!r}. Use um de: {', '.join(TIPOS_SUPORTADOS)}"
    )


def requisitos_do_tipo(vpn_type: str | None = None, *, mode: str | None = None) -> tuple[str, ...]:
    """Variáveis de ambiente exigidas pela tecnologia de VPN ativa.

    Em `VPN_MODE=host` devolve vazio: o túnel é estabelecido fora do processo.
    """
    if normalize_vpn_mode(mode) == "host":
        return ()
    try:
        return _classe_do_tipo(vpn_type or VPN_TYPE).requisitos_config()
    except ValueError:
        return ()
    except ImportError as e:
        logger.warning("[VPN Factory] backend indisponível para %s: %s", vpn_type, e)
        return ()


def _alvo_de_verificacao() -> tuple[str, int] | None:
    """Alvo TCP que comprova o túnel: VPN_PROBE_TARGET ou o host do ERP ativo."""
    from agent.vpn.host_managed import parse_alvo

    if VPN_PROBE_TARGET:
        return parse_alvo(VPN_PROBE_TARGET)

    perfil = resolve_erp_perfil()
    return parse_alvo(perfil.get("url") or perfil.get("host"))


def get_vpn(*, vpn_type: str | None = None, mode: str | None = None) -> VPNManager:
    """Devolve o VPNManager adequado a VPN_TYPE + VPN_MODE."""
    tipo = vpn_type or VPN_TYPE
    modo = normalize_vpn_mode(mode)
    logger.info("[VPN Factory] VPN_TYPE=%s VPN_MODE=%s", tipo, modo)

    if modo == "container":
        return _build_backend(tipo)

    from agent.vpn.host_managed import HostManagedVPN

    probe = None
    try:
        probe = _build_backend(tipo).is_connected
    except Exception as e:
        logger.debug("[VPN Factory] sem backend nativo para probe (%s): %s", tipo, e)

    return HostManagedVPN(
        probe=probe,
        alvo=_alvo_de_verificacao(),
        wait_seconds=VPN_HOST_WAIT_SECONDS,
        descricao=f"cliente {tipo} do host",
    )
