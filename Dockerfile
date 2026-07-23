# Imagem do agente Carol App RPA (runtime autônomo T3).
#
# Base bookworm (Debian 12) e NÃO trixie: o Web Agent do Protheus é Electron 17
# e depende da stack GTK com nomes pré-t64 (libgtk-3-0 etc.), que só existem no
# bookworm. Trocar a base quebra o Web Agent em silêncio, no runtime.
#
# Perfil Tezk42/FSB: WireGuard + Protheus SmartClient Web.

FROM python:3.12-slim-bookworm

WORKDIR /app

# ─── Dependências do sistema ─────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # VPN WireGuard (módulo no kernel do HOST; aqui só userspace de controle).
    wireguard-tools \
    iproute2 \
    ca-certificates \
    # Display virtual + dbus (modo tray do Electron)
    xvfb \
    dbus-x11 \
    imagemagick \
    # Runtime do Electron (Web Agent) — libappindicator via ayatana (symlink abaixo)
    libgtk-3-0 \
    libnotify4 \
    libnss3 \
    libnss3-tools \
    libxss1 \
    libxtst6 \
    libatspi2.0-0 \
    libsecret-1-0 \
    libuuid1 \
    libayatana-appindicator3-1 \
    libdbusmenu-glib4 \
    # Runtime do Chromium (Playwright)
    libglib2.0-0 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# ─── Dependências Python ─────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Chromium (Playwright) ───────────────────────────────────────────────────
RUN playwright install chromium

# ─── Instaladores de terceiros (todos opcionais) ─────────────────────────────
# Artefatos com download autenticado. Não versionados: coloque em files/ antes
# do build.
#
#   *WEB-AGENT*.TAR.GZ   Protheus — impressão, ficheiros locais, certificado
#
# Instalação condicional: build não quebra se o instalador ainda não estiver
# presente (lab com WEB_AGENT_FORWARD_HOST).
COPY files/ /tmp/files/
RUN set -eux; \
    apt-get update; \
    \
    web_agent="$(find /tmp/files -maxdepth 1 -iname '*WEB-AGENT*.TAR.GZ' | sort -r | head -n1 || true)"; \
    if [ -n "${web_agent}" ]; then \
        cd /tmp/files && tar -xzf "${web_agent}" && \
        apt-get install -y ./web-agent-*-linux-x64-release.deb && \
        ln -sf /usr/lib/x86_64-linux-gnu/libayatana-appindicator3.so.1 \
               /usr/lib/x86_64-linux-gnu/libappindicator3.so.1 && \
        test -f /opt/web-agent/web-agent && \
        # O .deb Linux 1.1.0 não inclui os certificados WSS; o instalador
        # Windows gera-os na 1.ª execução (totvs_certificate*). Sem eles o
        # SmartClient falha em wss://127.0.0.1:21021 (ERR_SSL_PROTOCOL_ERROR).
        if [ -f /tmp/files/totvs_certificate_CA.crt ] \
           && [ -f /tmp/files/totvs_certificate.crt ] \
           && [ -f /tmp/files/totvs_certificate_key.pem ]; then \
            cp /tmp/files/totvs_certificate_CA.crt \
               /tmp/files/totvs_certificate.crt \
               /tmp/files/totvs_certificate_key.pem \
               /opt/web-agent/; \
            if [ -f /tmp/files/cacert.pem ]; then \
                cp /tmp/files/cacert.pem /opt/web-agent/; \
            fi; \
            cp /opt/web-agent/totvs_certificate_CA.crt \
               /usr/local/share/ca-certificates/totvs_certificate_CA.crt; \
            update-ca-certificates; \
            echo "web-agent certificados WSS instalados"; \
        else \
            echo "AVISO: totvs_certificate*.crt/pem ausentes em files/ — WSS do Web Agent falhará"; \
        fi; \
        echo "web-agent instalado"; \
    else \
        echo "AVISO: instalador do Web Agent ausente em files/ — obrigatório para Protheus"; \
    fi; \
    \
    rm -rf /var/lib/apt/lists/* /tmp/files

# ─── Código ──────────────────────────────────────────────────────────────────
COPY agent/ agent/
COPY resources/ resources/

# Sem COPY do .env: os segredos entram por variável de ambiente na plataforma
# (ver `environments` no manifest.json). Embutir credenciais na imagem as
# tornaria legíveis por quem tiver acesso ao registry.

ENV AGENT_ENV=production \
    RUNTIME_MODE=t3 \
    VPN_MODE=container \
    VPN_TYPE=WIREGUARD \
    ERP_TYPE=protheus \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1

COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
