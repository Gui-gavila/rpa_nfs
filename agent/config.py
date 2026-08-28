"""Configuração centralizada do agente Carol App RPA (especialização Tezk42/FSB).

Lê `.env` e expõe constantes tipadas + resolvers de perfil.

Eixos parametrizáveis:

    ERP_TYPE      protheus                 → ErpAgent (único neste fork)
    SESSION_TYPE  browser                  → sessão de UI (Protheus)
    VPN_TYPE      WIREGUARD | WG           → backend de VPN

Eixos de runtime:

    RUNTIME_MODE  t2 (ponte Windows) | t3 (autônomo Docker)
    VPN_MODE      host (VPN por GUI no host) | container (VPN no próprio processo)

Nenhum import obriga credenciais de VPN ou de ERP: modos de lab podem usar
`SEM_VPN=1`, e o preflight declara o que realmente precisa.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_TRUTHY = ("1", "true", "yes", "sim", "on")


def _get_env(key: str, required: bool = True) -> str:
    """Lê variável de ambiente, falhando cedo quando obrigatória."""
    value = os.getenv(key)
    if required and not value:
        raise EnvironmentError(f"Variável de ambiente obrigatória ausente: {key}")
    return value or ""


def _flag(key: str, default: str = "") -> bool:
    """Lê variável de ambiente como booleano."""
    return (os.getenv(key, default) or "").strip().lower() in _TRUTHY


def _normalize(
    valor: str | None, aliases: dict[str, str], *, nome: str, default: str
) -> str:
    """Normaliza um valor contra um mapa de aliases, com erro explícito.

    Base de todos os `normalize_*`: mantém a mensagem de erro uniforme e sempre
    listando os valores aceitos, que é o que torna o `.env` auto-documentado.
    """
    raw = str(valor if valor is not None else default or "").strip().lower()
    if raw not in aliases:
        aceitos = "|".join(sorted(set(aliases.values())))
        raise ValueError(f"{nome} inválido: {valor!r}. Use {aceitos}")
    return aliases[raw]


# ---------------------------------------------------------------------------
# Ambiente e runtime
# ---------------------------------------------------------------------------

AGENT_ENV: str = os.getenv("AGENT_ENV", "development")
IS_PRODUCTION: bool = AGENT_ENV == "production"

# T2 = ponte Windows (worker .exe no RDP do cliente, VPN por GUI)
# T3 = autônomo (container Linux faz VPN → sessão remota → visão+teclado)
RUNTIME_MODE: str = os.getenv("RUNTIME_MODE", "t3")

_RUNTIME_ALIASES = {
    "t2": "t2", "ponte": "t2", "bridge": "t2", "worker": "t2", "windows": "t2",
    "t3": "t3", "autonomo": "t3", "autônomo": "t3", "docker": "t3", "container": "t3",
}


def normalize_runtime_mode(valor: str | None = None) -> str:
    """Normaliza RUNTIME_MODE para t2|t3."""
    return _normalize(valor, _RUNTIME_ALIASES, nome="RUNTIME_MODE", default=RUNTIME_MODE)


# Onde a VPN é estabelecida:
#   host      = lab: cliente WireGuard do SO; o processo só verifica o túnel
#   container = prod: o próprio processo sobe a VPN (wg-quick)
VPN_MODE: str = os.getenv("VPN_MODE", os.getenv("T3_VPN_MODE", "container"))
# Lab / T2: ignora estágio VPN (equivalente ao antigo --sem-vpn).
SEM_VPN: bool = _flag("SEM_VPN")

_VPN_MODE_ALIASES = {
    "host": "host", "lab": "host", "hibrido": "host", "híbrido": "host",
    "hybrid": "host", "gui": "host",
    "container": "container", "prod": "container", "production": "container",
    "linux": "container", "wg": "container", "wireguard": "container",
}


def normalize_vpn_mode(valor: str | None = None) -> str:
    """Normaliza VPN_MODE para host|container (aceita o legado T3_VPN_MODE)."""
    return _normalize(valor, _VPN_MODE_ALIASES, nome="VPN_MODE", default=VPN_MODE)


# ---------------------------------------------------------------------------
# ERP alvo
# ---------------------------------------------------------------------------

ERP_TYPE: str = os.getenv("ERP_TYPE", "protheus")

_ERP_ALIASES = {
    "protheus": "protheus", "totvs-protheus": "protheus", "p12": "protheus",
    "smartclient-web": "protheus",
}


def normalize_erp_type(valor: str | None = None) -> str:
    """Normaliza ERP_TYPE para protheus (único ERP deste fork)."""
    return _normalize(valor, _ERP_ALIASES, nome="ERP_TYPE", default=ERP_TYPE)


# ---------------------------------------------------------------------------
# Sessão remota (como a UI do ERP é alcançada)
# ---------------------------------------------------------------------------

# Vazio = derivar de ERP_TYPE + RUNTIME_MODE (ver resolve_session_type).
SESSION_TYPE: str = os.getenv("SESSION_TYPE", "")

_SESSION_ALIASES = {
    "browser": "browser", "playwright": "browser", "web": "browser", "chromium": "browser",
}


def normalize_session_type(valor: str | None) -> str:
    """Normaliza SESSION_TYPE para browser."""
    return _normalize(valor, _SESSION_ALIASES, nome="SESSION_TYPE", default="")

# Protheus SmartClient Web é alcançado direto por HTTP sobre a VPN — sem RDP.
_SESSION_PADRAO: dict[tuple[str, str], str] = {
    ("protheus", "t2"): "browser",
    ("protheus", "t3"): "browser",
}


def resolve_session_type(
    *,
    erp: str | None = None,
    runtime: str | None = None,
    session: str | None = None,
) -> str:
    """Resolve o tipo de sessão remota, derivando de ERP+runtime quando não fixado.

    SESSION_TYPE explícito sempre vence.
    """
    explicito = session if session is not None else SESSION_TYPE
    if (explicito or "").strip():
        return normalize_session_type(explicito)
    chave = (normalize_erp_type(erp), normalize_runtime_mode(runtime))
    if chave not in _SESSION_PADRAO:
        raise ValueError(
            f"Sem sessão padrão para erp={chave[0]} runtime={chave[1]}; defina SESSION_TYPE"
        )
    return _SESSION_PADRAO[chave]


# ---------------------------------------------------------------------------
# VPN (WireGuard — único backend deste fork)
# ---------------------------------------------------------------------------

VPN_TYPE: str = os.getenv("VPN_TYPE", "WIREGUARD")

# Cada backend declara o que precisa (`VPNManager.requisitos_config`) e o
# preflight cobra. Em VPN_MODE=host não há credencial no processo.
# Ver ADR 2026_07_20_requisitos-de-config-por-backend-vpn.
VPN_TIMEOUT_SECONDS: int = int(os.getenv("VPN_TIMEOUT_SECONDS", "40"))
VPN_TUN_WAIT_SECONDS: int = int(os.getenv("VPN_TUN_WAIT_SECONDS", "120"))

# VPN_MODE=host: o túnel é do host. Para confirmar que ele existe, testamos
# alcance TCP de um alvo que só a VPN enxerga.
# Vazio = derivar do host do ERP ativo (ver agent.vpn.factory).
VPN_PROBE_TARGET: str = os.getenv("VPN_PROBE_TARGET", "").strip()
VPN_HOST_WAIT_SECONDS: int = int(os.getenv("VPN_HOST_WAIT_SECONDS", "180"))

# WireGuard — autenticação por par de chaves no .conf (segredo).
# WIREGUARD_CONFIG materializa em runtime com 0600 e remove no cleanup.
# WIREGUARD_CONFIG_PATH é alternativa quando o .conf já está montado.
# WIREGUARD_DNS: nameservers internos (vírgula) em /etc/resolv.conf após o
# túnel — substitui a linha DNS= do .conf (proibida no container).
WIREGUARD_CONFIG: str = os.getenv("WIREGUARD_CONFIG", "")
WIREGUARD_CONFIG_PATH: str = os.getenv("WIREGUARD_CONFIG_PATH", "").strip()
WIREGUARD_INTERFACE: str = os.getenv("WIREGUARD_INTERFACE", "wg0").strip() or "wg0"
WIREGUARD_DNS: str = os.getenv("WIREGUARD_DNS", "").strip()


# ---------------------------------------------------------------------------
# Sessão: browser (Protheus SmartClient Web)
# ---------------------------------------------------------------------------

# O canvas do SmartClient Web não expõe DOM, então a automação usa coordenadas —
# o viewport precisa ser determinístico ou as coordenadas calibradas quebram.
BROWSER_WIDTH: int = int(os.getenv("BROWSER_WIDTH", "1280"))
BROWSER_HEIGHT: int = int(os.getenv("BROWSER_HEIGHT", "720"))
BROWSER_HEADLESS: bool = _flag("BROWSER_HEADLESS", "1" if IS_PRODUCTION else "0")
BROWSER_SLOW_MO_MS: int = int(
    os.getenv("BROWSER_SLOW_MO_MS", "0" if IS_PRODUCTION else "80")
)
BROWSER_LOCALE: str = os.getenv("BROWSER_LOCALE", "pt-BR")

# TOTVS Smart Client Web Agent (Electron): no Linux precisa ser subido pelo
# processo sob Xvfb; no Windows é gerenciado pelo SO.
# Lab Docker Desktop: sem binário na imagem, WEB_AGENT_FORWARD_HOST aponta ao
# Web Agent do host (ex.: host.docker.internal) — o SmartClient fala em
# 127.0.0.1:WEB_AGENT_PORT dentro do container.
WEB_AGENT_BIN: str = os.getenv("WEB_AGENT_BIN", "/opt/web-agent/web-agent")
WEB_AGENT_PORT: int = int(os.getenv("WEB_AGENT_PORT", "21021"))
WEB_AGENT_FORWARD_HOST: str = os.getenv("WEB_AGENT_FORWARD_HOST", "").strip()
# Porta no host quando o Web Agent só escuta em 127.0.0.1 (lab Docker Desktop).
# Ex.: proxy host 0.0.0.0:21022 → 127.0.0.1:21021; container usa FORWARD_PORT=21022.
WEB_AGENT_FORWARD_PORT: int = int(os.getenv("WEB_AGENT_FORWARD_PORT", "0") or "0")
DISPLAY: str = os.getenv("DISPLAY", ":99")


# ---------------------------------------------------------------------------
# ERP: Protheus
# ---------------------------------------------------------------------------

PROTHEUS_URL: str = os.getenv("PROTHEUS_URL", "")
PROTHEUS_USERNAME: str = os.getenv("PROTHEUS_USERNAME", "")
PROTHEUS_PASSWORD: str = os.getenv("PROTHEUS_PASSWORD", "")
PROTHEUS_PROGRAMA_INICIAL: str = os.getenv("PROTHEUS_PROGRAMA_INICIAL", "SIGAFISREM")
PROTHEUS_AMBIENTE_SERVIDOR: str = os.getenv("PROTHEUS_AMBIENTE_SERVIDOR", "P")
# Templates de visão separados por ERP: um fork usa um ERP, e misturar dezenas
# de PNGs de ERPs distintos numa pasta só torna a recalibração confusa.
PROTHEUS_RESOURCES_DIR: str = os.getenv("PROTHEUS_RESOURCES_DIR", "resources/protheus")
PROTHEUS_UI_LOAD_TIMEOUT_S: float = float(os.getenv("PROTHEUS_UI_LOAD_TIMEOUT_S", "40"))


def resolve_protheus_perfil() -> dict[str, str]:
    """Perfil do Protheus ativo (mesma forma de retorno dos demais resolvers)."""
    return {
        "erp": "protheus",
        "ambiente": PROTHEUS_AMBIENTE_SERVIDOR,
        "url": PROTHEUS_URL,
        "username": PROTHEUS_USERNAME,
        "password": PROTHEUS_PASSWORD,
        "programa": PROTHEUS_PROGRAMA_INICIAL,
        "resources_dir": PROTHEUS_RESOURCES_DIR,
        "label": f"Protheus {PROTHEUS_AMBIENTE_SERVIDOR} @ {PROTHEUS_URL}",
    }


def resolve_erp_perfil(erp: str | None = None) -> dict[str, str]:
    """Perfil do ERP ativo — entrada única para a fábrica de ErpAgent."""
    key = normalize_erp_type(erp)
    if key != "protheus":
        raise ValueError(f"ERP_TYPE não suportado neste fork: {key!r}")
    return resolve_protheus_perfil()


# ---------------------------------------------------------------------------
# Logs, artefatos e alertas
# ---------------------------------------------------------------------------

LOG_LEVEL: str = (os.getenv("LOG_LEVEL") or ("INFO" if IS_PRODUCTION else "DEBUG")).strip()
LOG_DIR: str = os.getenv("LOG_DIR", "").strip()
# Prefixo do log diário; default identifica o ERP para não misturar corridas.
# Destino vazio = `{FOLDER_FILES_AGENT_LYNN}/04_Logs/{YYYYMM}/<erp>-YYYYMMDD.log`.
LOG_PREFIX: str = os.getenv("LOG_PREFIX", "").strip() or normalize_erp_type()

# Destino vazio = `{FOLDER_FILES_AGENT_LYNN}/05_Screenshots/{YYYYMM}/`.
SCREENSHOTS_DIR: str = os.getenv("SCREENSHOTS_DIR", "").strip()

# Alerta operacional (SMTP) para falha em execução agendada.
ALERT_SMTP_HOST: str = os.getenv("ALERT_SMTP_HOST", "").strip()
ALERT_SMTP_PORT: int = int(os.getenv("ALERT_SMTP_PORT", "587"))
ALERT_SMTP_USER: str = os.getenv("ALERT_SMTP_USER", "").strip()
ALERT_SMTP_PASSWORD: str = os.getenv("ALERT_SMTP_PASSWORD", "")
ALERT_SMTP_FROM: str = os.getenv("ALERT_SMTP_FROM", "").strip()
ALERT_SMTP_TO: str = os.getenv("ALERT_SMTP_TO", "").strip()
ALERT_SMTP_TLS: bool = _flag("ALERT_SMTP_TLS", "1")


# ---------------------------------------------------------------------------
# Classificação NF TES 002 — data-plane (API / LYNN / share / deparas)
# ---------------------------------------------------------------------------
# Modo fake|http: fake = dublê (default quando URL/root vazios).
# Paths e tokens só via .env — nunca no código.

PROTHEUS_API_MODE: str = os.getenv("PROTHEUS_API_MODE", "fake").strip() or "fake"
PROTHEUS_API_BASE_URL: str = os.getenv("PROTHEUS_API_BASE_URL", "").strip()
PROTHEUS_API_TOKEN: str = os.getenv("PROTHEUS_API_TOKEN", "")
PROTHEUS_API_TIMEOUT_S: float = float(os.getenv("PROTHEUS_API_TIMEOUT_S", "30"))
# generic_query = Postman FSB; provisional = /nfs/... legado F2
PROTHEUS_API_STYLE: str = (
    os.getenv("PROTHEUS_API_STYLE", "generic_query").strip() or "generic_query"
)
PROTHEUS_API_TENANT_ID: str = os.getenv("PROTHEUS_API_TENANT_ID", "01").strip() or "01"
PROTHEUS_AC9_VERIFY: bool = os.getenv("PROTHEUS_AC9_VERIFY", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "sim",
)
# Lab P12 costuma exigir verify=False (certificado intermediário ausente).
PROTHEUS_API_SSL_VERIFY: bool = os.getenv(
    "PROTHEUS_API_SSL_VERIFY", "1"
).strip().lower() not in ("0", "false", "no", "nao", "não")

# Predicado SF1 para listagem + ValidarMudancaStatus (pré-coleta).
# vazio (default/produção) = F1_STATUS = '' | nao_vazio (lab) = F1_STATUS != ''
# Não afeta confirmar_classificada (pós-UI: classificada = status preenchido).
_SF1_STATUS_FILTRO_ALIASES = {
    "vazio": "vazio",
    "empty": "vazio",
    "eq": "vazio",
    "=": "vazio",
    "pendente": "vazio",
    "nao_vazio": "nao_vazio",
    "não_vazio": "nao_vazio",
    "ne": "nao_vazio",
    "!=": "nao_vazio",
    "preenchido": "nao_vazio",
    "lab": "nao_vazio",
}


def normalize_protheus_sf1_status_filtro(valor: str | None = None) -> str:
    """Normaliza PROTHEUS_SF1_STATUS_FILTRO para vazio|nao_vazio."""
    raw = (
        valor
        if valor is not None
        else os.getenv("PROTHEUS_SF1_STATUS_FILTRO", "vazio")
    )
    return _normalize(
        raw, _SF1_STATUS_FILTRO_ALIASES, nome="PROTHEUS_SF1_STATUS_FILTRO", default="vazio"
    )


PROTHEUS_SF1_STATUS_FILTRO: str = normalize_protheus_sf1_status_filtro()


def where_clause_f1_status_pendente(filtro: str | None = None) -> str:
    """Fragmento WHERE SF1 alinhado ao filtro (listagem)."""
    modo = normalize_protheus_sf1_status_filtro(
        filtro if filtro is not None else PROTHEUS_SF1_STATUS_FILTRO
    )
    if modo == "nao_vazio":
        return "F1_STATUS != ''"
    return "F1_STATUS = ''"


def status_bate_filtro_pendente(status: str, filtro: str | None = None) -> bool:
    """True se o F1_STATUS atual ainda é elegível segundo o filtro (pré-coleta)."""
    modo = normalize_protheus_sf1_status_filtro(
        filtro if filtro is not None else PROTHEUS_SF1_STATUS_FILTRO
    )
    s = (status or "").strip()
    if modo == "nao_vazio":
        return s != ""
    return s == ""


LYNN_API_MODE: str = os.getenv("LYNN_API_MODE", "fake").strip() or "fake"
# Host DTA (sem path). Ex.: https://totvs.dta.totvs.ai
LYNN_BASE_URL: str = (
    os.getenv("LYNN_BASE_URL") or os.getenv("LYNN_API_BASE_URL") or ""
).strip()
# Legado / alias: se só LYNN_API_BASE_URL apontar ao host, LYNN_BASE_URL herda acima.
LYNN_API_BASE_URL: str = os.getenv("LYNN_API_BASE_URL", "").strip()
# workflow = Flows homolog; agent = Agents LYNN (produção FSB).
LYNN_RUN_MODE: str = (os.getenv("LYNN_RUN_MODE", "workflow") or "workflow").strip()
# api_key = x-dta-api-key; bearer = Authorization JWT. Vazio → default por RUN_MODE.
LYNN_AUTH_MODE: str = os.getenv("LYNN_AUTH_MODE", "").strip()
LYNN_PROJECT: str = os.getenv("LYNN_PROJECT", "").strip()
LYNN_WORKFLOW_ID: str = os.getenv("LYNN_WORKFLOW_ID", "").strip()
LYNN_AGENT_ID: str = os.getenv("LYNN_AGENT_ID", "").strip()
# Credencial: api_key (sk-…) ou Bearer JWT. Alias cruzado TOKEN/KEY.
LYNN_API_TOKEN: str = os.getenv("LYNN_API_TOKEN", "") or os.getenv("LYNN_API_KEY", "")
LYNN_API_KEY: str = os.getenv("LYNN_API_KEY", "").strip()
LYNN_API_TIMEOUT_S: float = float(os.getenv("LYNN_API_TIMEOUT_S", "120"))
LYNN_MESSAGE: str = os.getenv(
    "LYNN_MESSAGE",
    "Segue Documento Fiscal",
).strip()

PDF_SHARE_MODE: str = os.getenv("PDF_SHARE_MODE", "fake").strip() or "fake"
# Origem TI (UNC FSB). Vazio = sem stage; PDFs já devem estar em 01_NF_Classificar.
# Ex. produção: \\10.250.64.60\rpa$\
PDF_SHARE_SOURCE: str = os.getenv("PDF_SHARE_SOURCE", "").strip()
# Pastas relativas opcionais sob a origem (sem listar a UNC). Ex.: 202608,202607
PDF_SHARE_SOURCE_SUBDIRS: str = os.getenv("PDF_SHARE_SOURCE_SUBDIRS", "").strip()

DEPARA_NATUREZA_DESPESA_PATH: str = os.getenv("DEPARA_NATUREZA_DESPESA_PATH", "").strip()
DEPARA_CODIGO_SERVICO_PATH: str = os.getenv("DEPARA_CODIGO_SERVICO_PATH", "").strip()
DEPARA_NATUREZA_RENDIMENTO_PATH: str = os.getenv(
    "DEPARA_NATUREZA_RENDIMENTO_PATH", ""
).strip()
DEPARA_VENCIMENTO_ESPECIAL_PATH: str = os.getenv(
    "DEPARA_VENCIMENTO_ESPECIAL_PATH", ""
).strip()

# Orquestração classificar_nf (F3)
# Casa única do agente. Subpastas: 01_NF_Classificar, 02_NF_Processadas_Lynn,
# 03_Classificadas_Protheus, 04_Logs, 05_Screenshots (+ ANOMES).
# FOLDER_FILES_AGENT_LYNN = casa dos ficheiros 01–05; FOLDER_WORKER_AGENT_LYNN = publish futuro.
# CLASSIFICADOR_NF_ROOT / FOLDER_ROOT_AGENT_LYNN = aliases legados.
# PDF_SHARE_ROOT deixa de existir no .env; deriva de 01_NF_Classificar.
# WORK_DIR vazio = {ROOT}/01_NF_Classificar/{YYYYMM} via caminhos.py.
FOLDER_FILES_AGENT_LYNN: str = (
    os.getenv("FOLDER_FILES_AGENT_LYNN")
    or os.getenv("FOLDER_ROOT_AGENT_LYNN")  # legado
    or os.getenv("CLASSIFICADOR_NF_ROOT")
    or r"C:\AgentLynn\ClassificadorNF"
).strip()
FOLDER_ROOT_AGENT_LYNN: str = FOLDER_FILES_AGENT_LYNN  # alias legado
CLASSIFICADOR_NF_ROOT: str = FOLDER_FILES_AGENT_LYNN
PDF_SHARE_ROOT: str = str(Path(FOLDER_FILES_AGENT_LYNN) / "01_NF_Classificar")
# Casa futura dos artefactos publish (ainda sem consumidores no código).
FOLDER_WORKER_AGENT_LYNN: str = (
    os.getenv("FOLDER_WORKER_AGENT_LYNN") or r"C:\AgentLynn\Worker"
).strip()
CLASSIFICAR_NF_CHECKPOINT_DIR: str = (
    os.getenv("CLASSIFICAR_NF_CHECKPOINT_DIR") or "./data/classificar_nf"
).strip()
CLASSIFICAR_NF_CHECKPOINT_PATH: str = os.getenv(
    "CLASSIFICAR_NF_CHECKPOINT_PATH", ""
).strip()
CLASSIFICAR_NF_WORK_DIR: str = os.getenv("CLASSIFICAR_NF_WORK_DIR", "").strip()
CLASSIFICAR_NF_CONTROLE_XLSX: str = os.getenv(
    "CLASSIFICAR_NF_CONTROLE_XLSX", ""
).strip()
CLASSIFICAR_NF_NIVEL_MAX: int = int(os.getenv("CLASSIFICAR_NF_NIVEL_MAX", "0") or "0")
# 0 = sem teto; 1+ = bloco da corrida (próximas N elegíveis; leftover PRONTO_UI conta no teto).
CLASSIFICAR_NF_LIMITE: int = int(os.getenv("CLASSIFICAR_NF_LIMITE", "0") or "0")
# 1 = um bloco por invocação (Carol agenda o próximo); 2+ = repetir data+UI no mesmo processo.
CLASSIFICAR_NF_CICLOS: int = max(1, int(os.getenv("CLASSIFICAR_NF_CICLOS", "1") or "1"))
CLASSIFICAR_NF_FORCAR: bool = _flag("CLASSIFICAR_NF_FORCAR", "0")
# Lab: seed Fake API/LYNN/PDF + deparas minimos (so se os tres modos forem fake).
CLASSIFICAR_NF_LAB_SEED: bool = _flag("CLASSIFICAR_NF_LAB_SEED", "0")

# UI MATA103 — real (lab/prod) | simulado (testes / fila sem canvas)
MATA103_MODO: str = os.getenv("MATA103_MODO", "real").strip() or "real"
MATA103_SETTLE_S: float = float(os.getenv("MATA103_SETTLE_S", "1.2"))

# Relatório fiscal (SMTP de negócio — separado de ALERT_SMTP_*)
REPORT_SMTP_HOST: str = os.getenv("REPORT_SMTP_HOST", "").strip()
REPORT_SMTP_PORT: int = int(os.getenv("REPORT_SMTP_PORT", "587"))
REPORT_SMTP_USER: str = os.getenv("REPORT_SMTP_USER", "").strip()
REPORT_SMTP_PASSWORD: str = os.getenv("REPORT_SMTP_PASSWORD", "")
REPORT_SMTP_FROM: str = os.getenv("REPORT_SMTP_FROM", "").strip()
REPORT_SMTP_TO: str = os.getenv("REPORT_SMTP_TO", "").strip()
REPORT_SMTP_TLS: bool = _flag("REPORT_SMTP_TLS", "1")
# ciclo = e-mail a cada worker (lab); esgotado = só quando não resta LYNN nem Pronto UI.
REPORT_SMTP_FREQUENCIA: str = (
    os.getenv("REPORT_SMTP_FREQUENCIA", "ciclo").strip() or "ciclo"
)
