"""Contrato base dos gerenciadores de VPN."""

from __future__ import annotations

from abc import ABC, abstractmethod


class VPNManager(ABC):
    """Interface abstrata para provedores de VPN."""

    @abstractmethod
    def connect(self) -> bool:
        """Conecta à VPN. True se o túnel ficou ativo."""

    @abstractmethod
    def disconnect(self) -> None:
        """Desconecta da VPN."""

    @abstractmethod
    def is_connected(self) -> bool:
        """True se o túnel está ativo."""

    @classmethod
    def requisitos_config(cls) -> tuple[str | tuple[str, ...], ...]:
        """Variáveis de ambiente sem as quais este backend não opera.

        Consultado pelo preflight *antes* de instanciar qualquer coisa — daí ser
        método de classe. Cada tecnologia tem um modelo de autenticação próprio
        (usuário+senha+MFA, credenciais em argumento, par de chaves estático), e
        cobrar de todas o mesmo conjunto reprovaria backends que legitimamente
        não usam credencial.

        Cada item é o nome de uma variável obrigatória, OU uma tupla de nomes da
        qual pelo menos um precisa estar definido (fontes alternativas — ex.: o
        WireGuard aceita o config por conteúdo ou por caminho).

        Default vazio: quem não declara nada não exige nada — caso do
        HostManagedVPN, que verifica o túnel em vez de estabelecê-lo.

        Ver ADR 2026_07_20_requisitos-de-config-por-backend-vpn.
        """
        return ()
