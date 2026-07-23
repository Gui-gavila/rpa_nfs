"""Backend VPN WireGuard (Linux / container, via wg-quick).

O mais simples dos backends no ciclo de vida — sem prompt, sem credencial, sem
MFA: a autenticação é o par de chaves Curve25519 no arquivo `.conf`. Por isso é
também o único que permite operação verdadeiramente autônoma (o risco de MFA
documentado em Architecture.md §16 não se aplica aqui).

WireGuard não é um cliente que roda em espaço de usuário como os demais: a parte
que move os pacotes vive no kernel. `wg-quick`/`wg` são a casca fina que fala com
ela. Logo o módulo precisa estar no host — confirmado kernel 6.x na plataforma
alvo, então usamos o caminho de kernel (sem fallback wireguard-go).

Segurança da chave privada
--------------------------
O conteúdo do `.conf` carrega a chave privada. Ele NÃO pode ser versionado nem
embutido na imagem. Entra por `WIREGUARD_CONFIG` (variável de ambiente, que a
plataforma trata como segredo) e é materializado em runtime num diretório
privado (`0700`) com o arquivo em `0600`, removido no `disconnect()`. A
alternativa `WIREGUARD_CONFIG_PATH` aponta um `.conf` já presente no host — nesse
caso o arquivo é usado como está e não é removido (não fomos nós que o criamos).

Este backend nunca registra o conteúdo do config em log.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from agent.vpn.base import VPNManager

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 45


class WireGuardVPN(VPNManager):
    """VPN WireGuard via wg-quick, para o runtime autônomo (container Linux)."""

    @classmethod
    def requisitos_config(cls) -> tuple[str | tuple[str, ...], ...]:
        # Uma das duas fontes de config precisa existir — não ambas.
        return (("WIREGUARD_CONFIG", "WIREGUARD_CONFIG_PATH"),)

    def __init__(
        self,
        *,
        config_content: str = "",
        config_path: str = "",
        interface: str = "wg0",
        dns_servers: str = "",
        timeout: int = CONNECT_TIMEOUT,
    ) -> None:
        self.config_content = config_content or ""
        self.config_path = (config_path or "").strip()
        # Nome da interface. Quando o config vem por caminho, o wg-quick a nomeia
        # pelo basename do arquivo — então é ele que manda nesse caso.
        if self.config_path:
            self.interface = Path(self.config_path).stem
        else:
            self.interface = (interface or "wg0").strip() or "wg0"
        self.dns_servers = [
            s.strip() for s in (dns_servers or "").split(",") if s.strip()
        ]
        self.timeout = timeout
        # Preenchidos na materialização; usados no teardown.
        self._conf_ativo: Path | None = None
        self._dir_proprio: Path | None = None
        self._resolv_backup: str | None = None
        logger.info(
            "[WireGuardVPN] Inicializado interface=%s fonte=%s dns=%s",
            self.interface,
            "conteúdo" if self.config_content else ("caminho" if self.config_path else "(nenhuma)"),
            ",".join(self.dns_servers) or "(nenhum)",
        )

    # --- materialização do config ------------------------------------------

    def _materializar(self) -> Path | None:
        """Resolve o `.conf` a usar. Materializa o conteúdo com 0600 se preciso.

        Devolve o caminho do config, ou None se não há config configurado.
        Define `_conf_ativo` e `_dir_proprio` (este só quando fomos nós que
        criamos o arquivo, para saber o que remover no teardown).
        """
        if self.config_path:
            caminho = Path(self.config_path)
            if not caminho.is_file():
                logger.error("[WireGuardVPN] WIREGUARD_CONFIG_PATH não existe: %s", caminho)
                return None
            self._conf_ativo = caminho
            self._dir_proprio = None  # não criamos: não removemos
            return caminho

        if not self.config_content.strip():
            logger.error(
                "[WireGuardVPN] sem config: defina WIREGUARD_CONFIG (conteúdo) "
                "ou WIREGUARD_CONFIG_PATH (arquivo)"
            )
            return None

        # Diretório privado (mkdtemp já cria com 0700), arquivo em 0600. A chave
        # privada não deve ficar legível por outros processos da máquina.
        diretorio = Path(tempfile.mkdtemp(prefix="wg-"))
        conf = diretorio / f"{self.interface}.conf"
        conf.write_text(self.config_content, encoding="utf-8")
        os.chmod(conf, 0o600)
        self._conf_ativo = conf
        self._dir_proprio = diretorio
        logger.info("[WireGuardVPN] config materializado (0600) para interface=%s", self.interface)
        return conf

    def _limpar_arquivos(self) -> None:
        """Remove o config materializado. No-op para config fornecido por caminho."""
        if self._dir_proprio is not None:
            shutil.rmtree(self._dir_proprio, ignore_errors=True)
        self._dir_proprio = None
        self._conf_ativo = None

    # --- ciclo de vida ------------------------------------------------------

    def connect(self) -> bool:
        if self.is_connected():
            logger.info("[WireGuardVPN] túnel já ativo (interface=%s)", self.interface)
            self._aplicar_dns()
            return True

        wgquick = shutil.which("wg-quick")
        if not wgquick:
            logger.error(
                "[WireGuardVPN] wg-quick não encontrado no PATH "
                "(instale wireguard-tools; no Windows use o cliente WireGuard e VPN_MODE=host)"
            )
            return False

        conf = self._materializar()
        if conf is None:
            return False

        logger.info("[WireGuardVPN] subindo interface=%s", self.interface)
        try:
            resultado = subprocess.run(
                [wgquick, "up", str(conf)],
                capture_output=True, text=True, timeout=self.timeout,
            )
        except Exception as e:
            logger.error("[WireGuardVPN] falha ao executar wg-quick up: %s", e)
            self._limpar_arquivos()
            return False

        if resultado.returncode != 0:
            # stderr do wg-quick não expõe a chave; é seguro registrar.
            logger.error("[WireGuardVPN] wg-quick up falhou: %s", (resultado.stderr or "").strip())
            self._limpar_arquivos()
            return False

        if self.is_connected():
            logger.info("[WireGuardVPN] túnel ativo (interface=%s)", self.interface)
            self._aplicar_dns()
            return True

        # up retornou 0 mas a interface não aparece: desfaz para não deixar
        # estado pendurado nem o config em disco.
        logger.error("[WireGuardVPN] wg-quick up ok, mas interface %s não subiu", self.interface)
        self.disconnect()
        return False

    def _aplicar_dns(self) -> None:
        """Grava nameservers internos em /etc/resolv.conf (após o túnel).

        Substitui a linha DNS= do .conf, que o wg-quick recusa sem resolvconf.
        """
        if not self.dns_servers:
            return
        resolv = Path("/etc/resolv.conf")
        try:
            anterior = resolv.read_text(encoding="utf-8") if resolv.is_file() else ""
            self._resolv_backup = anterior
            linhas = [f"nameserver {s}" for s in self.dns_servers]
            for line in anterior.splitlines():
                low = line.strip().lower()
                if low.startswith("nameserver") or not line.strip():
                    continue
                linhas.append(line)
            resolv.write_text("\n".join(linhas) + "\n", encoding="utf-8")
            logger.info(
                "[WireGuardVPN] DNS interno aplicado: %s",
                ",".join(self.dns_servers),
            )
        except OSError as e:
            logger.warning("[WireGuardVPN] não foi possível aplicar DNS: %s", e)

    def _restaurar_dns(self) -> None:
        if self._resolv_backup is None:
            return
        try:
            Path("/etc/resolv.conf").write_text(self._resolv_backup, encoding="utf-8")
        except OSError:
            pass
        self._resolv_backup = None

    def disconnect(self) -> None:
        self._restaurar_dns()
        wgquick = shutil.which("wg-quick")
        if wgquick and self._conf_ativo is not None:
            try:
                subprocess.run(
                    [wgquick, "down", str(self._conf_ativo)],
                    capture_output=True, text=True, timeout=self.timeout,
                )
                logger.info("[WireGuardVPN] interface %s derrubada", self.interface)
            except Exception as e:
                logger.error("[WireGuardVPN] erro no wg-quick down: %s", e)
        # A remoção do config vem depois do down: o wg-quick reabre o arquivo
        # para executar diretivas PostDown antes de encerrar.
        self._limpar_arquivos()

    def is_connected(self) -> bool:
        """True se a interface WireGuard existe e está configurada.

        `wg show <iface>` sai com código != 0 quando a interface não existe — é
        a checagem mais específica; não inspecionamos nomes de interface fixos
        como os backends PPP/tun fazem.
        """
        try:
            resultado = subprocess.run(
                ["wg", "show", self.interface],
                capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            logger.error("[WireGuardVPN] comando 'wg' não encontrado (wireguard-tools)")
            return False
        except Exception as e:
            logger.debug("[WireGuardVPN] erro ao consultar wg show: %s", e)
            return False

        ativo = resultado.returncode == 0 and bool((resultado.stdout or "").strip())
        logger.debug("[WireGuardVPN] interface %s: %s", self.interface, "UP" if ativo else "DOWN")
        return ativo
