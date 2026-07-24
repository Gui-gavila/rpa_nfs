"""Agente do ERP Protheus Web (SmartClient Web).

Esqueleto de especialização Tezk42 (FSB): implementa autenticação e entrada no
ERP. A rotina de negócio específica entra em `run()`.

Anatomia da tela (o que justifica a técnica usada)
--------------------------------------------------
O SmartClient Web renderiza via protocolo binário num `<canvas>`
(`totvstec_remote_type=5`). Depois da autenticação, o DOM não expõe inputs
nem botões e o CDP não atravessa o engine embutido. Consequência: a partir
de `/session-settings`, a automação é por teclado e coordenada.

A autenticação em si, porém, costuma ser HTML (PO UI) dentro de um *iframe*
do app-root — não na página `/webapp/` raiz. Ali usamos `fill_dom`/`click_dom`
(que já vasculham frames). Ambientes antigos ainda podem exibir a tela HTML
de Programa Inicial / Ambiente antes do login, ou credenciais só no canvas.

Sequência típica atual:
  /webapp/ → iframe /login (PO UI) → credenciais DOM →
  /session-settings → Entrar (canvas) → [aviso] → tela principal.

Sequência legada (ainda suportada):
  /webapp/ (Programa/Ambiente HTML) → OK → /login (canvas teclado) → …
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent.erp.base import ErpAgent

logger = logging.getLogger(__name__)

# Coordenadas de canvas — válidas para o viewport configurado (padrão 1280x720).
# Só existem porque o canvas não expõe elementos; se o viewport mudar, recalibre.
BTN_ENTRAR = (718, 627)         # "Entrar" na tela de seleção de sessão
BTN_FECHAR_AVISO = (953, 155)   # "x" do modal "Ambiente de Homologação"

SETTLE_S = 2.0    # estabilização após uma transição de tela
ERP_LOAD_S = 12.0  # carga do ERP após "Entrar" (não há sinal de rota confiável)
KEY_DELAY_MS = 50  # o TWebEngine perde teclas se a digitação for instantânea

# Login PO UI (iframe app-root …/login)
SEL_LOGIN = 'input[name="login"]'
SEL_PASSWORD = 'input[name="password"]'
SEL_ENTRAR = 'button.po-button:has-text("Entrar")'

# Tela legada Programa Inicial / Ambiente
SEL_OK = 'button:has-text("OK")'

# Menu SIGACOM (sidebar HTML do Protheus Web)
MENU_CAMINHO_PRODUTOS = ("Atualizações", "Cadastros", "Produtos")
# Templates opcionais em resources/protheus/ (fallback se DOM falhar)
MENU_TEMPLATES = {
    "Atualizações": "menu-atualizacoes.png",
    "Cadastros": "menu-cadastros.png",
    "Produtos": "menu-produtos.png",
}
TMPL_DIALOG_OK = "dialog-ok.png"
MENU_CLICK_TIMEOUT_S = 20.0
DIALOG_OK_TIMEOUT_S = 25.0


class ProtheusAgent(ErpAgent):
    """Autentica no Protheus Web e entra na tela principal do ERP."""

    def __init__(
        self,
        surface: Any,
        *,
        username: str,
        password: str,
        programa: str,
        ambiente: str,
        screenshots_dir: str | Path = "./screenshots",
        nav_timeout_s: float = 40.0,
        btn_entrar: tuple[int, int] = BTN_ENTRAR,
        btn_fechar_aviso: tuple[int, int] = BTN_FECHAR_AVISO,
    ) -> None:
        super().__init__(surface)
        self.username = username
        self.password = password
        self.programa = programa
        self.ambiente = ambiente
        self.screenshots_dir = Path(screenshots_dir)
        self.nav_timeout_s = nav_timeout_s
        self.btn_entrar = btn_entrar
        self.btn_fechar_aviso = btn_fechar_aviso
        self._screenshots: list[str] = []

    # --- apoio --------------------------------------------------------------

    def screenshot(self, nome: str) -> str | None:
        """Grava evidência da tela atual. Nunca interrompe o fluxo."""
        try:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            caminho = self.screenshots_dir / f"{nome}.png"
            self.surface.screenshot_para(str(caminho))
            self._screenshots.append(str(caminho))
            return str(caminho)
        except Exception as e:
            logger.warning("[ProtheusAgent] screenshot '%s' falhou: %s", nome, e)
            return None

    def _aguardar_rota(self, trecho: str) -> bool:
        """Aguarda a rota interna do SmartClient. False se a Surface não a expõe."""
        aguardar = getattr(self.surface, "aguardar_rota", None)
        if aguardar is None:
            logger.warning(
                "[ProtheusAgent] Surface sem rastreio de rota — seguindo por tempo"
            )
            self.surface.sleep(SETTLE_S)
            return True
        return bool(aguardar(trecho, self.nav_timeout_s))

    def _contar_dom(self, seletor: str) -> int | None:
        """Contagem de elementos DOM, ou None se a Surface não expõe a API."""
        contar = getattr(self.surface, "contar_dom", None)
        if contar is None:
            return None
        try:
            return int(contar(seletor))
        except Exception:
            return 0

    def _aguardar_login_ok(self) -> bool:
        """True se chegou em /session-settings; False se erro de auth ou timeout."""
        import time

        deadline = time.time() + self.nav_timeout_s
        while time.time() < deadline:
            rota = getattr(self.surface, "rota", "") or ""
            if "/session-settings" in rota:
                return True
            if (self._contar_dom("text=Usuário não autenticado") or 0) > 0:
                logger.error("[ProtheusAgent] autenticação recusada pelo ERP (usuário/senha)")
                return False
            time.sleep(0.05)

        return False

    def _aguardar_saida_session_settings(self) -> bool:
        """True quando saímos de /session-settings ou a home do ERP aparece.

        A rota interna às vezes permanece em session-settings enquanto o frame
        principal já montou o menu (Compras, Log Off, etc.).
        """
        import time

        deadline = time.time() + self.nav_timeout_s
        while time.time() < deadline:
            rota = getattr(self.surface, "rota", "") or ""
            if rota and "/session-settings" not in rota and "/login" not in rota:
                if "about:blank" not in rota and "totvsnews" not in rota:
                    return True
            # Botão Entrar do PO some ao entrar; home traz estes textos.
            n_entrar = self._contar_dom(SEL_ENTRAR)
            if n_entrar is not None and n_entrar == 0:
                return True
            if (self._contar_dom("text=Trocar módulo") or 0) > 0:
                return True
            if (self._contar_dom("text=Log Off") or 0) > 0:
                return True
            time.sleep(0.05)

        rota = getattr(self.surface, "rota", "") or ""
        if rota and "/session-settings" not in rota and "/login" not in rota:
            if "about:blank" not in rota and "totvsnews" not in rota:
                return True
        if (self._contar_dom("text=Trocar módulo") or 0) > 0:
            return True
        if (self._contar_dom("text=Log Off") or 0) > 0:
            return True
        return False

    def _aguardar_html_auth(self) -> None:
        """Espera o formulário HTML (PO ou Programa/Ambiente) ou a rota /login.

        A BrowserSession marca a sessão pronta ainda em `/webapp/`, antes do
        iframe do app-root montar o login — sem esta espera caímos cedo demais
        no fallback de teclado do canvas.
        """
        if getattr(self.surface, "contar_dom", None) is None:
            return

        import time

        deadline = time.time() + self.nav_timeout_s
        while time.time() < deadline:
            if (self._contar_dom(SEL_LOGIN) or 0) > 0 or (self._contar_dom(SEL_OK) or 0) > 0:
                return
            rota = getattr(self.surface, "rota", "") or ""
            if "/login" in rota:
                self.surface.sleep(0.5)
                if (self._contar_dom(SEL_LOGIN) or 0) > 0:
                    return
                # /login sem input name=login → credenciais no canvas.
                return
            time.sleep(0.05)
        logger.warning("[ProtheusAgent] formulário HTML de autenticação não apareceu a tempo")

    def _preencher_programa_ambiente(self) -> bool:
        """Tela legada Programa/Ambiente. True se preencheu; False se não aplica."""
        n_login = self._contar_dom(SEL_LOGIN)
        if n_login is not None and n_login > 0:
            return False
        n_ok = self._contar_dom(SEL_OK)
        if n_ok is not None and n_ok == 0:
            return False
        # Sem API de contagem, não adivinhamos a tela legada.
        if n_login is None and n_ok is None:
            return False

        self.surface.fill_dom('input[type="text"]', self.programa, indice=0)
        self.surface.fill_dom('input[type="text"]', self.ambiente, indice=1)
        self.surface.click_dom(SEL_OK)
        logger.info("[ProtheusAgent] tela Programa/Ambiente confirmada")
        return True

    def _autenticar_dom_po(self) -> bool:
        """Login HTML PO UI (iframe). True se usou esse caminho."""
        n_login = self._contar_dom(SEL_LOGIN)
        if n_login is not None and n_login == 0:
            return False

        self.surface.fill_dom(SEL_LOGIN, self.username)
        self.surface.fill_dom(SEL_PASSWORD, self.password)
        self.surface.click_dom(SEL_ENTRAR)
        logger.info("[ProtheusAgent] credenciais enviadas via DOM (PO UI)")
        return True

    def _autenticar_canvas_teclado(self) -> None:
        """Fallback: campo de usuário no canvas já com foco; navega por teclado."""
        logger.info("[ProtheusAgent] credenciais via teclado (canvas)")
        self.surface.type_text(self.username, delay_ms=KEY_DELAY_MS)
        self.surface.press("tab")
        self.surface.sleep(0.5)
        self.surface.type_text(self.password, delay_ms=KEY_DELAY_MS)
        self.surface.sleep(0.5)
        self.surface.press("enter")

    def _seletores_item_menu(self, rotulo: str) -> list[str]:
        """Seletores DOM para um item do menu lateral (rótulo pode vir com contagem)."""
        return [
            f'a:has-text("{rotulo}")',
            f'span:has-text("{rotulo}")',
            f'div:has-text("{rotulo}")',
            f'text={rotulo}',
        ]

    def _clicar_item_menu(self, rotulo: str) -> bool:
        """Clica num item do menu: DOM primeiro, template de visão como fallback."""
        for seletor in self._seletores_item_menu(rotulo):
            n = self._contar_dom(seletor)
            if n is not None and n > 0:
                try:
                    self.surface.click_dom(seletor)
                    logger.info("[ProtheusAgent] menu DOM '%s' via %s", rotulo, seletor)
                    return True
                except Exception as e:
                    logger.debug("[ProtheusAgent] click_dom %s falhou: %s", seletor, e)

        template = MENU_TEMPLATES.get(rotulo)
        click_image = getattr(self.surface, "click_image", None)
        if template and callable(click_image):
            if click_image(
                template,
                confidence=0.72,
                timeout_s=MENU_CLICK_TIMEOUT_S,
            ):
                logger.info("[ProtheusAgent] menu imagem '%s' (%s)", rotulo, template)
                return True

        logger.error("[ProtheusAgent] item de menu não encontrado: %s", rotulo)
        return False

    def _confirmar_dialogo_ok(self) -> bool:
        """Confirma o diálogo que abre ao lançar a rotina (botão OK)."""
        # PO / HTML
        for seletor in (SEL_OK, 'button:has-text("Ok")', 'text=OK'):
            n = self._contar_dom(seletor)
            if n is not None and n > 0:
                try:
                    self.surface.click_dom(seletor)
                    logger.info("[ProtheusAgent] diálogo OK via DOM (%s)", seletor)
                    return True
                except Exception as e:
                    logger.debug("[ProtheusAgent] click OK DOM falhou: %s", e)

        click_image = getattr(self.surface, "click_image", None)
        if callable(click_image) and click_image(
            TMPL_DIALOG_OK,
            confidence=0.72,
            timeout_s=DIALOG_OK_TIMEOUT_S,
        ):
            logger.info("[ProtheusAgent] diálogo OK via imagem")
            return True

        # Último recurso: Enter costuma confirmar o diálogo padrão do Protheus.
        try:
            self.surface.press("enter")
            logger.info("[ProtheusAgent] diálogo OK via Enter")
            return True
        except Exception as e:
            logger.error("[ProtheusAgent] não foi possível confirmar OK: %s", e)
            return False

    def _abrir_cadastro_produtos(self) -> bool:
        """Menu: Atualizações → Cadastros → Produtos → OK."""
        logger.info(
            "[ProtheusAgent] navegando menu: %s",
            " → ".join(MENU_CAMINHO_PRODUTOS),
        )
        for rotulo in MENU_CAMINHO_PRODUTOS:
            if not self._clicar_item_menu(rotulo):
                self.screenshot(f"protheus_menu_falha_{rotulo.lower()}")
                return False
            self.surface.sleep(SETTLE_S)
            self.screenshot(f"protheus_menu_{rotulo.lower()}")

        self.surface.sleep(SETTLE_S)
        if not self._confirmar_dialogo_ok():
            self.screenshot("protheus_produtos_ok_falha")
            return False
        self.surface.sleep(SETTLE_S)
        self.screenshot("protheus_produtos")
        logger.info("[ProtheusAgent] cadastro de Produtos aberto")
        return True

    # --- contrato ErpAgent --------------------------------------------------

    def login(self) -> bool:
        """Autentica no Protheus. Espera a sessão já na URL do SmartClient.

        Quem navega até a URL é a BrowserSession; aqui tratamos a autenticação
        HTML (PO UI ou Programa/Ambiente) e, se preciso, o canvas legado.
        """
        logger.info(
            "[ProtheusAgent] login programa=%s ambiente=%s usuario=%s",
            self.programa, self.ambiente, self.username,
        )

        try:
            self._aguardar_html_auth()

            if self._preencher_programa_ambiente():
                if not self._aguardar_rota("/login"):
                    logger.warning(
                        "[ProtheusAgent] rota /login não detectada — seguindo assim mesmo"
                    )
                self.surface.sleep(SETTLE_S)

            self.screenshot("protheus_login")

            if not self._autenticar_dom_po():
                self._autenticar_canvas_teclado()
        except AttributeError:
            logger.error(
                "[ProtheusAgent] esta especialização exige uma PlaywrightSurface "
                "(a autenticação HTML do Protheus usa DOM real)"
            )
            return False
        except Exception as e:
            logger.error("[ProtheusAgent] falha na autenticação: %s", e)
            self.screenshot("protheus_tela_inicial_falha")
            return False

        # Comprova autenticação pela rota, ou falha cedo se o PO UI mostrar erro.
        if self._aguardar_login_ok():
            self.surface.sleep(SETTLE_S)
            self.screenshot("protheus_session_settings")
            logger.info("[ProtheusAgent] login OK")
            return True

        self.screenshot("protheus_login_falha")
        logger.error("[ProtheusAgent] login não avançou (credenciais ou fluxo inesperado)")
        return False

    def run(self, **kwargs: Any) -> dict[str, Any]:
        """Entra no ERP e abre Cadastros → Produtos (SIGACOM).

        Fluxo: session-settings → tela principal →
        Atualizações → Cadastros → Produtos → OK.
        """
        resultado: dict[str, Any] = {
            "ok": False,
            "erro": None,
            "modulo": self.programa,
            "screenshots": self._screenshots,
        }
        try:
            logger.info("[ProtheusAgent] confirmando sessão")
            # session-settings é PO UI (HTML no iframe). Preferir DOM; coordenada
            # só como fallback para ambientes antigos em canvas.
            if (self._contar_dom(SEL_ENTRAR) or 0) > 0:
                self.surface.click_dom(SEL_ENTRAR)
            else:
                self.surface.click(*self.btn_entrar)

            if not self._aguardar_saida_session_settings():
                self.screenshot("protheus_erp_falha")
                resultado["erro"] = "protheus_entrada_falhou: session-settings não avançou"
                logger.error("[ProtheusAgent] %s", resultado["erro"])
                resultado["screenshots"] = self._screenshots
                return resultado

            # Se a home já está visível, não precisa esperar a carga completa.
            ja_na_home = (self._contar_dom("text=Trocar módulo") or 0) > 0 or (
                self._contar_dom("text=Log Off") or 0
            ) > 0
            if not ja_na_home:
                self.surface.sleep(ERP_LOAD_S)
                # Ambientes de homologação exibem um modal de aviso. O clique é
                # inócuo quando ele não existe (cai em área vazia do cabeçalho).
                self.surface.click(*self.btn_fechar_aviso)
                self.surface.sleep(SETTLE_S * 2)
            else:
                self.surface.sleep(SETTLE_S)

            self.screenshot("protheus_erp_principal")
            logger.info("[ProtheusAgent] entrada no ERP concluída")

            if not self._abrir_cadastro_produtos():
                resultado["erro"] = "protheus_menu_produtos_falhou"
                logger.error("[ProtheusAgent] %s", resultado["erro"])
                resultado["screenshots"] = self._screenshots
                return resultado

            resultado["ok"] = True
        except Exception as e:
            logger.error("[ProtheusAgent] falha ao entrar no ERP: %s", e, exc_info=True)
            self.screenshot("protheus_erp_falha")
            resultado["erro"] = f"protheus_entrada_falhou: {e}"

        resultado["screenshots"] = self._screenshots
        return resultado
