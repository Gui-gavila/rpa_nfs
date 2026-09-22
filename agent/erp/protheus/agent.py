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
AGUARDAR_TELA_S = 10.0  # teto para a próxima tela aparecer (home, session-settings)
KEY_DELAY_MS = 50  # o TWebEngine perde teclas se a digitação for instantânea

# Login PO UI (iframe app-root …/login)
SEL_LOGIN = 'input[name="login"]'
SEL_PASSWORD = 'input[name="password"]'
SEL_ENTRAR = 'button.po-button:has-text("Entrar")'

# Tela legada Programa Inicial / Ambiente
SEL_OK = 'button:has-text("OK")'

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
        from agent.ops_alert import gravar_screenshot_ui

        caminho = gravar_screenshot_ui(
            surface=self.surface,
            contexto=nome,
            pasta=self.screenshots_dir,
        )
        if caminho:
            self._screenshots.append(str(caminho))
            return str(caminho)
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

    def _preencher_filial_session_settings(self, filial_codigo: str) -> bool:
        """Preenche Filial na tela HTML /session-settings (antes de Entrar)."""
        fil = (filial_codigo or "").strip()
        if not fil:
            return False
        por_rotulo = getattr(self.surface, "fill_dom_por_rotulo", None)
        if por_rotulo:
            try:
                if por_rotulo("Filial", fil):
                    logger.info(
                        "[ProtheusAgent] session-settings filial=%s via rotulo",
                        fil,
                    )
                    self.surface.sleep(0.4)
                    return True
            except Exception:
                pass
        fill = getattr(self.surface, "fill_dom", None)
        if fill is None:
            logger.warning(
                "[ProtheusAgent] session-settings filial=%s não preenchida (DOM)",
                fil,
            )
            return False
        # Só seletores amarrados ao rótulo Filial — po-input genérico dá timeout.
        candidatos: list[tuple[str, int]] = [
            ('po-field:has-text("Filial") input', 0),
            ('po-combo:has-text("Filial") input', 0),
            ('.po-field:has-text("Filial") input', 0),
            ('label:has-text("Filial") ~ * input', 0),
        ]
        for sel, indice in candidatos:
            try:
                if (self._contar_dom(sel) or 0) <= indice:
                    continue
                fill(sel, fil, indice=indice)
                logger.info(
                    "[ProtheusAgent] session-settings filial=%s via %s[%s]",
                    fil,
                    sel,
                    indice,
                )
                self.surface.sleep(0.4)
                return True
            except Exception:
                continue
        logger.warning(
            "[ProtheusAgent] session-settings filial=%s não preenchida (DOM)",
            fil,
        )
        return False

    def _entrar_erp_principal(
        self, *, filial_codigo: str = ""
    ) -> tuple[bool, str | None]:
        """Session-settings → tela principal. (ok, erro_slug)."""
        logger.info("[ProtheusAgent] confirmando sessão")
        if filial_codigo:
            self._preencher_filial_session_settings(filial_codigo)
        if (self._contar_dom(SEL_ENTRAR) or 0) > 0:
            self.surface.click_dom(SEL_ENTRAR)
        else:
            self.surface.click(*self.btn_entrar)

        if not self._aguardar_saida_session_settings():
            self.screenshot("protheus_erp_falha")
            return False, "protheus_entrada_falhou: session-settings não avançou"

        # Espera home real (menu lateral). Session-settings pode ficar em «Carregando…».
        import time

        deadline = time.time() + AGUARDAR_TELA_S
        ja_na_home = False
        while time.time() < deadline:
            ja_na_home = (self._contar_dom("text=Trocar módulo") or 0) > 0 or (
                self._contar_dom("text=Atualizações") or 0
            ) > 0
            if ja_na_home:
                break
            self.surface.sleep(0.5)
        if not ja_na_home:
            self.surface.click(*self.btn_fechar_aviso)
            self.surface.sleep(SETTLE_S * 2)
            ja_na_home = (self._contar_dom("text=Trocar módulo") or 0) > 0 or (
                self._contar_dom("text=Atualizações") or 0
            ) > 0
        else:
            self.surface.sleep(SETTLE_S)

        if not ja_na_home:
            self.screenshot("protheus_erp_falha")
            return False, "protheus_entrada_falhou: home do ERP não apareceu"

        self.screenshot("protheus_erp_principal")
        logger.info("[ProtheusAgent] entrada no ERP concluída")
        return True, None

    def _trocar_filial_erp(self, filial_codigo: str) -> tuple[bool, str | None]:
        """Log Off → session-settings com a nova filial → home."""
        fil = (filial_codigo or "").strip()
        logger.info("[ProtheusAgent] trocar_filial=%s", fil)
        if not fil:
            return False, "protheus_troca_filial_falhou: filial vazia"
        click_dom = getattr(self.surface, "click_dom", None)
        sleep = getattr(self.surface, "sleep", None)
        if click_dom is None:
            return self._entrar_erp_principal(filial_codigo=fil)
        if (self._contar_dom("text=Log Off") or 0) <= 0:
            return False, "protheus_troca_filial_falhou: Log Off ausente"
        try:
            click_dom("text=Log Off")
        except Exception as e:
            return False, f"protheus_troca_filial_falhou: {type(e).__name__}"
        if sleep:
            sleep(SETTLE_S)
        for sel in (
            "button:has-text('Sim')",
            "po-button:has-text('Sim')",
            "button:has-text('Confirmar')",
        ):
            if (self._contar_dom(sel) or 0) > 0:
                try:
                    click_dom(sel)
                except Exception:
                    pass
                if sleep:
                    sleep(SETTLE_S)
                break
        import time

        deadline = time.time() + AGUARDAR_TELA_S
        while time.time() < deadline:
            rota = getattr(self.surface, "rota", "") or ""
            if "/session-settings" in rota or (self._contar_dom(SEL_ENTRAR) or 0) > 0:
                return self._entrar_erp_principal(filial_codigo=fil)
            if "/login" in rota or (self._contar_dom(SEL_LOGIN) or 0) > 0:
                if not self.login():
                    return False, "protheus_troca_filial_falhou: login"
                return self._entrar_erp_principal(filial_codigo=fil)
            if sleep:
                sleep(0.4)
            else:
                time.sleep(0.4)
        self.screenshot("protheus_troca_filial_falha")
        return False, "protheus_troca_filial_falhou: session-settings não voltou"

    def _run_classificar_nf(self, **kwargs: Any) -> dict[str, Any]:
        """Entra no ERP e classifica a fila_ui via MATA103; atualiza checkpoint."""
        from agent import config
        from agent.domain.classificacao_nf.status import StatusNf
        from agent.erp.protheus.mata103 import FILIAL_HOLDING, Mata103Ui
        from agent.integrations.protheus_api import criar_protheus_api_client
        from agent.jobs.classificar_nf.checkpoint import Checkpoint, ItemCheckpoint

        resultado: dict[str, Any] = {
            "ok": False,
            "erro": None,
            "modulo": "MATA103",
            "screenshots": self._screenshots,
            "ui_pendente": False,
            "classificadas": 0,
            "falhas_ui": 0,
        }
        try:
            fila_raw = kwargs.get("fila_ui") or []
            itens: list[ItemCheckpoint] = []
            for raw in fila_raw:
                if isinstance(raw, ItemCheckpoint):
                    itens.append(raw)
                elif isinstance(raw, dict):
                    itens.append(ItemCheckpoint.from_dict(raw))

            prontos = [i for i in itens if i.status == StatusNf.PRONTO_UI]
            ok, erro = self._entrar_erp_principal(filial_codigo=FILIAL_HOLDING)
            if not ok:
                resultado["erro"] = erro
                resultado["screenshots"] = self._screenshots
                return resultado

            ck_path = kwargs.get("checkpoint_path") or config.CLASSIFICAR_NF_CHECKPOINT_PATH
            ck = Checkpoint.carregar(ck_path) if ck_path else None

            ui = Mata103Ui(
                self.surface,
                resources_dir=config.PROTHEUS_RESOURCES_DIR,
                modo=config.MATA103_MODO,
                settle_s=float(config.MATA103_SETTLE_S),
            )
            api = criar_protheus_api_client()

            classificadas = 0
            falhas = 0
            for item in prontos:
                logger.info(
                    "[ProtheusAgent] MATA103 item %s status=%s",
                    item.chave,
                    item.status,
                )
                res = ui.classificar_item(item)
                if res.ok:
                    # Commit do F1_STATUS pode atrasar alguns segundos após o Salvar UI.
                    confirmada = False
                    status_api = "-"
                    consultar = getattr(api, "consultar_f1_status", None)
                    for tentativa in range(5):
                        confirmada = api.confirmar_classificada(
                            filial_codigo=item.filial_codigo,
                            numero_nf=item.numero_nf,
                            codigo_fornecedor=item.codigo_fornecedor,
                        )
                        if consultar:
                            try:
                                lido = consultar(
                                    filial_codigo=item.filial_codigo,
                                    numero_nf=item.numero_nf,
                                    codigo_fornecedor=item.codigo_fornecedor,
                                )
                                status_api = (
                                    "-" if lido is None else (lido or "(vazio)")
                                )
                            except Exception:
                                status_api = "?"
                        logger.info(
                            "[ProtheusAgent] confirmacao_api:chave=%s|"
                            "F1_STATUS=%s|ok=%s|tentativa=%s",
                            item.chave,
                            status_api,
                            confirmada,
                            tentativa + 1,
                        )
                        if confirmada or ui.simulado:
                            break
                        logger.info(
                            "[ProtheusAgent] confirmação API pendente %s tentativa=%s",
                            item.chave,
                            tentativa + 1,
                        )
                        sleep = getattr(self.surface, "sleep", None)
                        if sleep:
                            sleep(1.2)
                        else:
                            import time

                            time.sleep(1.2)
                    if confirmada or ui.simulado:
                        item.status = StatusNf.CLASSIFICADO
                        item.motivo = None
                        classificadas += 1
                        try:
                            from agent.jobs.classificar_nf.caminhos import (
                                mover_para_classificadas_protheus,
                            )

                            novo = mover_para_classificadas_protheus(
                                item.pdf_path
                            )
                            if novo is not None:
                                item.pdf_path = str(novo)
                                logger.info(
                                    "[ProtheusAgent] movido_03:chave=%s|pdf=%s",
                                    item.chave,
                                    novo,
                                )
                        except Exception as e:
                            logger.warning(
                                "[ProtheusAgent] move 02→03 falhou chave=%s: %s",
                                item.chave,
                                e,
                            )
                        try:
                            from agent.jobs.classificar_nf.caminhos import (
                                caminhos_de_config,
                            )
                            from agent.reporting.controle_vivo import (
                                FLAG_SIM,
                                carregar_indice,
                                salvar_indice,
                                upsert_indice,
                            )
                            from agent.reporting.enriquecer_controle import (
                                agora_iso_local,
                            )

                            controle = (
                                config.CLASSIFICAR_NF_CONTROLE_XLSX or ""
                            ).strip() or caminhos_de_config().get(
                                "controle_xlsx", ""
                            )
                            if controle:
                                indice = carregar_indice(controle)
                                upsert_indice(
                                    indice,
                                    {
                                        "COD_FILIAL": item.filial_codigo,
                                        "NUMERO_NF": item.numero_nf,
                                        "COD_FORNECEDOR": item.codigo_fornecedor,
                                        "STATUS": StatusNf.CLASSIFICADO,
                                        "MOTIVO": "",
                                        "STATUS_CLASSIFICACAO_PROTHEUS": (
                                            status_api
                                            if status_api
                                            not in ("-", "?", "(vazio)", "")
                                            else FLAG_SIM
                                        ),
                                        "TIMESTAMP SAIDA": agora_iso_local(),
                                    },
                                    forcar=(
                                        "STATUS",
                                        "MOTIVO",
                                        "STATUS_CLASSIFICACAO_PROTHEUS",
                                        "TIMESTAMP SAIDA",
                                    ),
                                )
                                salvar_indice(controle, indice)
                        except Exception as e:
                            logger.warning(
                                "[ProtheusAgent] planilha Protheus falhou chave=%s: %s",
                                item.chave,
                                e,
                            )
                    else:
                        item.status = StatusNf.NAO_CLASSIFICADO
                        item.motivo = (
                            "Interno - Status Classificada não confirmado na API"
                        )
                        falhas += 1
                else:
                    item.status = res.status
                    item.motivo = res.motivo
                    falhas += 1
                if ck is not None:
                    ck.upsert(item)
                    ck.salvar()

            resultado["ok"] = True
            resultado["classificadas"] = classificadas
            resultado["falhas_ui"] = falhas
            resultado["n_fila_ui"] = len(itens)
            if not itens:
                resultado["aviso"] = "fila_ui_vazia"
            logger.info(
                "[ProtheusAgent] MATA103 fim classificadas=%s falhas=%s",
                classificadas,
                falhas,
            )
        except Exception as e:
            logger.error("[ProtheusAgent] classificar_nf falhou: %s", e, exc_info=True)
            self.screenshot("protheus_erp_falha")
            resultado["erro"] = f"protheus_mata103_falhou: {e}"
        resultado["screenshots"] = self._screenshots
        return resultado

    def run(self, **kwargs: Any) -> dict[str, Any]:
        """Rotina de negócio conforme `fluxo`.

        - default / login: smoke até a tela principal do ERP (sem menu Cadastros)
        - classificar_nf: entrada ERP + fila UI (MATA103)
        """
        fluxo = (kwargs.get("fluxo") or kwargs.get("agente") or "").strip().lower()
        if fluxo in ("classificar_nf", "classificacao_nf", "tes002"):
            return self._run_classificar_nf(**kwargs)

        resultado: dict[str, Any] = {
            "ok": False,
            "erro": None,
            "modulo": self.programa,
            "screenshots": self._screenshots,
        }
        try:
            ok, erro = self._entrar_erp_principal()
            if not ok:
                resultado["erro"] = erro
                logger.error("[ProtheusAgent] %s", erro)
                resultado["screenshots"] = self._screenshots
                return resultado

            logger.info("[ProtheusAgent] smoke login: tela principal OK")
            resultado["ok"] = True
        except Exception as e:
            logger.error("[ProtheusAgent] falha ao entrar no ERP: %s", e, exc_info=True)
            self.screenshot("protheus_erp_falha")
            resultado["erro"] = f"protheus_entrada_falhou: {e}"

        resultado["screenshots"] = self._screenshots
        return resultado
