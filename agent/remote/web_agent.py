"""TOTVS Smart Client Web Agent — processo auxiliar do Protheus Web.

O SmartClient Web delega ao Web Agent (aplicação Electron) operações que o
browser não pode fazer sozinho: impressão, acesso a ficheiros locais, leitura de
certificado. Sem ele escutando em 127.0.0.1, o ERP abre mas falha nessas ações.

No Windows o Web Agent é instalado e gerido pelo SO. No container Linux ele
precisa ser iniciado pelo processo — e como é Electron em modo tray, exige um
display: daí o Xvfb no entrypoint.

Lab Docker Desktop em Windows: se o binário Linux não estiver na imagem, dá para
encaminhar `127.0.0.1:porta` para o Web Agent do host (`WEB_AGENT_FORWARD_HOST`,
tipicamente `host.docker.internal`), desde que o tray do Windows esteja ativo.
Com `VPN_MODE=container` o WIREGUARD_DNS substitui o resolver do Docker — chame
`ancorar_destino_forward` *antes* da VPN para gravar o IP do host.

Produção Carol App deve instalar o `.deb` via `files/*WEB-AGENT*.TAR.GZ`.
"""

from __future__ import annotations

import logging
import select
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT_BOOT_S = 30
_forward_lock = threading.Lock()
_forward_ativo: tuple | None = None
# hostname → IP resolvido antes de a VPN trocar o DNS (lab Docker Desktop).
_destino_ips: dict[str, str] = {}
_tls_lock = threading.Lock()
_tls_ativo: tuple | None = None

# Offset da porta HTTP interna quando o shim TLS ocupa WEB_AGENT_PORT.
_TLS_BACKEND_OFFSET = 10000
_CERT_CRT = "totvs_certificate.crt"
_CERT_KEY = "totvs_certificate_key.pem"
_CERT_CA = "totvs_certificate_CA.crt"


def _parece_ip(host: str) -> bool:
    try:
        socket.inet_aton(host)
        return True
    except OSError:
        return False


def ancorar_destino_forward(host: str) -> str:
    """Resolve e memoriza o IP do host de forward *antes* da VPN.

    Após `WIREGUARD_DNS`, nomes como `host.docker.internal` deixam de resolver
    (o /etc/resolv.conf já não aponta ao DNS embutido do Docker). O IP do
    gateway do Desktop (ex. 192.168.65.254) continua alcançável via eth0.
    """
    host = (host or "").strip()
    if not host:
        return ""
    if _parece_ip(host):
        _destino_ips[host] = host
        return host
    try:
        ip = socket.gethostbyname(host)
    except OSError as e:
        logger.warning("[WebAgent] não foi possível ancorar %s: %s", host, e)
        return _destino_ips.get(host, "")
    _destino_ips[host] = ip
    logger.info("[WebAgent] destino de forward ancorado: %s -> %s", host, ip)
    return ip


def resolver_destino_forward(host: str) -> str:
    """IP do destino de forward (âncora pré-VPN ou resolução ao vivo)."""
    host = (host or "").strip()
    if not host:
        return ""
    if _parece_ip(host):
        return host
    if host in _destino_ips:
        return _destino_ips[host]
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        return ""
    _destino_ips[host] = ip
    return ip


def porta_aberta(host: str, porta: int, timeout: float = 1.0) -> bool:
    """True se houver alguém escutando em host:porta."""
    try:
        with socket.create_connection((host, porta), timeout=timeout):
            return True
    except OSError:
        return False


def _pipe(origem: socket.socket, destino: socket.socket) -> None:
    """Copia bytes entre sockets (TCP ou SSL); um thread por direção."""
    try:
        while True:
            try:
                dados = origem.recv(65536)
            except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                continue
            except (ssl.SSLError, OSError):
                break
            if not dados:
                break
            try:
                destino.sendall(dados)
            except OSError:
                break
    except OSError:
        pass
    finally:
        for s in (origem, destino):
            try:
                s.close()
            except OSError:
                pass


def _servir_forward(listen_porta: int, destino_host: str, destino_porta: int) -> None:
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind(("127.0.0.1", listen_porta))
    servidor.listen(32)
    logger.info(
        "[WebAgent] forward 127.0.0.1:%s -> %s:%s",
        listen_porta, destino_host, destino_porta,
    )
    while True:
        try:
            cliente, _ = servidor.accept()
        except OSError:
            break
        try:
            remoto = socket.create_connection((destino_host, destino_porta), timeout=5)
        except OSError as e:
            logger.debug("[WebAgent] forward destino indisponível: %s", e)
            cliente.close()
            continue
        threading.Thread(target=_pipe, args=(cliente, remoto), daemon=True).start()
        threading.Thread(target=_pipe, args=(remoto, cliente), daemon=True).start()


def _iniciar_forward(
    destino_host: str, listen_porta: int, destino_porta: int | None = None
) -> bool:
    """Abre proxy local para o Web Agent do host. Idempotente por destino."""
    global _forward_ativo
    dest_porta = int(destino_porta or listen_porta)
    host_nome = destino_host.strip()
    host_ip = resolver_destino_forward(host_nome)
    if not host_ip:
        logger.error(
            "[WebAgent] destino de forward sem IP: %s "
            "(ancore com ancorar_destino_forward antes da VPN)",
            host_nome or "(vazio)",
        )
        return False
    destino = (host_ip, dest_porta)

    with _forward_lock:
        if _forward_ativo == (destino[0], dest_porta, listen_porta) and porta_aberta(
            "127.0.0.1", listen_porta
        ):
            return True
        if not porta_aberta(destino[0], destino[1], timeout=3.0):
            logger.error(
                "[WebAgent] destino de forward inacessível: %s:%s "
                "(no Docker Desktop: Web Agent no Windows; se só escuta em "
                "127.0.0.1 e o Desktop não o expõe, use proxy em 0.0.0.0)",
                destino[0], destino[1],
            )
            return False
        t = threading.Thread(
            target=_servir_forward,
            args=(listen_porta, destino[0], destino[1]),
            name="web-agent-forward",
            daemon=True,
        )
        t.start()
        _forward_ativo = (destino[0], dest_porta, listen_porta)

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if porta_aberta("127.0.0.1", listen_porta):
            logger.info("[WebAgent] forward ativo na porta %s", listen_porta)
            return True
        time.sleep(0.1)
    logger.error("[WebAgent] forward não abriu a porta local %s", listen_porta)
    return False


def _certs_wss(diretorio: Path) -> tuple[Path, Path, Path | None] | None:
    """Certificado/chave TOTVS para WSS (gerados na instalação Windows)."""
    crt = diretorio / _CERT_CRT
    key = diretorio / _CERT_KEY
    if not (crt.is_file() and key.is_file()):
        return None
    ca = diretorio / _CERT_CA
    return crt, key, ca if ca.is_file() else None


def _servir_tls_shim(
    listen_porta: int,
    backend_porta: int,
    certfile: Path,
    keyfile: Path,
    cafile: Path | None,
) -> None:
    """TLS em listen_porta → HTTP/WS do Web Agent em backend_porta.

    O binário Linux 1.1.0 escuta HTTP puro; o SmartClient atual exige wss://.
    """
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # Cadeia completa quando a CA está disponível (evita alerta em clientes
    # que não confiam só no leaf).
    if cafile is not None:
        cadeia = certfile.parent / "totvs_certificate_fullchain.pem"
        cadeia.write_text(
            certfile.read_text(encoding="utf-8")
            + "\n"
            + cafile.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        contexto.load_cert_chain(str(cadeia), str(keyfile))
    else:
        contexto.load_cert_chain(str(certfile), str(keyfile))

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind(("127.0.0.1", listen_porta))
    servidor.listen(32)
    logger.info(
        "[WebAgent] TLS shim 127.0.0.1:%s -> 127.0.0.1:%s",
        listen_porta, backend_porta,
    )
    while True:
        try:
            cliente, _ = servidor.accept()
        except OSError:
            break
        try:
            tls_cliente = contexto.wrap_socket(cliente, server_side=True)
        except ssl.SSLError as e:
            logger.warning("[WebAgent] TLS handshake falhou: %s", e)
            try:
                cliente.close()
            except OSError:
                pass
            continue
        try:
            remoto = socket.create_connection(("127.0.0.1", backend_porta), timeout=5)
        except OSError as e:
            logger.warning("[WebAgent] backend HTTP indisponível: %s", e)
            try:
                tls_cliente.close()
            except OSError:
                pass
            continue
        logger.debug(
            "[WebAgent] TLS sessão encaminhada para backend :%s", backend_porta
        )
        threading.Thread(target=_pipe, args=(tls_cliente, remoto), daemon=True).start()
        threading.Thread(target=_pipe, args=(remoto, tls_cliente), daemon=True).start()


def _iniciar_tls_shim(
    listen_porta: int,
    backend_porta: int,
    certfile: Path,
    keyfile: Path,
    cafile: Path | None,
) -> bool:
    global _tls_ativo
    with _tls_lock:
        if _tls_ativo == (listen_porta, backend_porta) and porta_aberta(
            "127.0.0.1", listen_porta
        ):
            return True
        t = threading.Thread(
            target=_servir_tls_shim,
            args=(listen_porta, backend_porta, certfile, keyfile, cafile),
            name="web-agent-tls-shim",
            daemon=True,
        )
        t.start()
        _tls_ativo = (listen_porta, backend_porta)

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if porta_aberta("127.0.0.1", listen_porta):
            logger.info("[WebAgent] TLS shim ativo na porta %s", listen_porta)
            return True
        time.sleep(0.1)
    logger.error("[WebAgent] TLS shim não abriu a porta %s", listen_porta)
    return False


def _aguardar_porta(porta: int, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if porta_aberta("127.0.0.1", porta):
            return True
        time.sleep(1)
    return False


def garantir_web_agent(
    *,
    binario: str,
    porta: int,
    timeout_s: float = TIMEOUT_BOOT_S,
    forward_host: str = "",
    forward_port: int = 0,
) -> bool:
    """Garante o Web Agent escutando em 127.0.0.1. Idempotente.

    Ordem: porta já aberta → forward (lab, se configurado) → binário local
    (+ TLS shim se houver certs).
    """
    if porta_aberta("127.0.0.1", porta):
        logger.info("[WebAgent] já escutando na porta %s", porta)
        return True

    # Lab Docker Desktop: forward tem prioridade mesmo com .deb na imagem —
    # o binário Linux 1.1.0 falha o secure handshake sob wss://.
    if forward_host.strip():
        dest_porta = int(forward_port or porta)
        destino_ip = resolver_destino_forward(forward_host)
        logger.info(
            "[WebAgent] forward configurado → %s:%s%s",
            forward_host.strip(),
            dest_porta,
            f" ({destino_ip})" if destino_ip and destino_ip != forward_host.strip() else "",
        )
        return _iniciar_forward(forward_host.strip(), porta, dest_porta)

    caminho = Path(binario) if binario else None
    if caminho is not None and caminho.exists():
        certs = _certs_wss(caminho.parent)
        # Binário Linux 1.1.0 = HTTP; SmartClient exige wss → sobe HTTP numa
        # porta interna e o shim TLS na porta pública.
        backend_porta = porta + _TLS_BACKEND_OFFSET if certs else porta
        cmd = [
            str(caminho),
            "--tray",
            "--port", str(backend_porta),
            "--no-sandbox",
            "--locallog", "1",
        ]
        logger.info("[WebAgent] iniciando: %s", " ".join(cmd))
        try:
            subprocess.Popen(
                cmd,
                cwd=str(caminho.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            logger.error("[WebAgent] falha ao iniciar: %s", e, exc_info=True)
            return False

        if not _aguardar_porta(backend_porta, timeout_s):
            logger.error(
                "[WebAgent] não abriu a porta %s em %ss", backend_porta, timeout_s
            )
            return False
        logger.info("[WebAgent] HTTP pronto na porta %s", backend_porta)

        if certs:
            crt, key, ca = certs
            logger.info(
                "[WebAgent] certificados WSS encontrados; ativando TLS shim → :%s",
                porta,
            )
            if not _iniciar_tls_shim(porta, backend_porta, crt, key, ca):
                return False
        else:
            logger.warning(
                "[WebAgent] sem %s/%s — SmartClient com wss:// pode falhar",
                _CERT_CRT, _CERT_KEY,
            )
        return True

    logger.error(
        "[WebAgent] binário não encontrado: %s "
        "(coloque *WEB-AGENT*.TAR.GZ em files/ ou defina WEB_AGENT_FORWARD_HOST)",
        binario or "(vazio)",
    )
    return False
