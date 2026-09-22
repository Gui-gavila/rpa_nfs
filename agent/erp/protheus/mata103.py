"""Automação UI da rotina MATA103 (Documento de Entrada — classificar).

O SmartClient Web é canvas: teclado + templates opcionais em
`resources/protheus/mata103/`. Sequências padrão são ponto de partida e
devem ser recalibradas no lab FSB (coordenadas/viewport).

Modo `simulado`: percorre a lógica sem Surface (testes / dry-run de fila).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.domain.classificacao_nf.status import MOTIVOS, StatusNf
from agent.jobs.classificar_nf.checkpoint import ItemCheckpoint

logger = logging.getLogger(__name__)

# Códigos de retenção do CR (fixos na UI).
COD_RETENCAO_IR = "1708"
COD_RETENCAO_PCC = "5952"

SETTLE_S = 1.2
AGUARDAR_TELA_S = 10.0  # teto para rotina/filtro/formulário aparecerem
ROTINA = "MATA103"
FILIAL_HOLDING = "0101"

# `campo-filtro-numero.png` ancora o TÍTULO do F12 («através de perguntas»),
# não o rótulo Número. Offsets até Número e Fornecedor (lab 1280×720).
# Após o Fornecedor o SX1 foca Filial sozinho — sem Tab/clique extra.
_FILTRO_DX_INPUT = 140
_FILTRO_DY_NUMERO = 43
_FILTRO_DY_FORNECEDOR = 65


@dataclass
class ResultadoUiNf:
    ok: bool
    status: str
    motivo: str | None = None
    detalhe: str = ""


class Mata103Ui:
    """Driver de classificação na MATA103."""

    def __init__(
        self,
        surface: Any | None = None,
        *,
        resources_dir: str | Path = "resources/protheus",
        modo: str = "real",
        settle_s: float = SETTLE_S,
        key_delay_ms: int = 50,
    ) -> None:
        self.surface = surface
        self.resources_dir = Path(resources_dir)
        self.mata_dir = self.resources_dir / "mata103"
        self.modo = (modo or "real").strip().lower()
        self.settle_s = settle_s
        self.key_delay_ms = key_delay_ms
        self._aberta = False
        self._falha_filtro: str | None = None
        self.acoes: list[str] = []

    @property
    def simulado(self) -> bool:
        return self.modo in ("simulado", "fake", "dry")

    def _log(self, acao: str) -> None:
        self.acoes.append(acao)
        logger.info("[MATA103] %s", acao)

    def _sleep(self) -> None:
        if self.simulado or self.surface is None:
            return
        sleep = getattr(self.surface, "sleep", None)
        if sleep:
            sleep(self.settle_s)

    def _press(self, tecla: str) -> None:
        self._log(f"press:{tecla}")
        if self.simulado or self.surface is None:
            return
        self.surface.press(tecla)

    def _type(self, texto: str) -> None:
        self._log(f"type:{texto}")
        if self.simulado or self.surface is None:
            return
        self.surface.type_text(str(texto), delay_ms=self.key_delay_ms)

    def _preencher_filial_dialogo_teclado(self, filial_codigo: str) -> None:
        """Grava Filial no diálogo AdvPL sem clicar coordenadas frágeis.

        Lab FSB: foco inicial = Data base. Tab×2 chega em Filial
        (Data → Grupo → Filial). Clique em (580,318) neste viewport
        acertava a Data e gerava 04/01/2026 a partir de «0401».
        """
        fil = (filial_codigo or "").strip()
        if not fil:
            return
        # Sai da Data base sem apagá-la.
        self._press("tab")
        self._press("tab")
        self._press("control+a")
        self._type(fil)
        self._press("tab")
        self._log(f"type_filial_dialog_tab:{fil}")

    def _preencher_filial_filtro_foco_erp(self, filial_codigo: str) -> None:
        """Grava Filial no F12 sem Tab/clique: o ERP já avançou o foco após o Fornecedor."""
        fil = (filial_codigo or "").strip()
        if not fil:
            return
        self._sleep()
        self._type_campo(fil)
        self._log(f"type_filtro_filial_foco_erp:{fil}")

    def _evidencia(self, nome: str) -> None:
        if self.simulado:
            return
        from agent.ops_alert import gravar_screenshot_ui

        dest = gravar_screenshot_ui(surface=self.surface, contexto=nome)
        if dest:
            self._log(f"screenshot:{dest.name}")

    def _template(self, nome: str) -> Path:
        return self.mata_dir / nome

    def _click_template(
        self,
        nome: str,
        *,
        timeout_s: float = AGUARDAR_TELA_S,
        offset_x: int = 0,
        offset_y: int = 0,
        confidence: float = 0.72,
    ) -> bool:
        path = self._template(nome)
        self._log(f"click_template:{nome}")
        if self.simulado or self.surface is None:
            return True
        click_image = getattr(self.surface, "click_image", None)
        if click_image is None or not path.is_file():
            return False
        # VisionMixin resolve por nome relativo a resources_dir da surface;
        # passamos caminho sob mata103 via resources_dir do agente.
        rel = f"mata103/{nome}"
        return bool(
            click_image(
                rel,
                timeout_s=timeout_s,
                confidence=confidence,
                offset_x=offset_x,
                offset_y=offset_y,
            )
        )

    def abrir_rotina(self, *, filial_codigo: str = "") -> bool:
        """Abre MATA103 a partir da tela principal.

        Lab FSB (2026-08-13): o campo Pesquisar não expõe sugestões no DOM —
        a abertura estável é menu Atualizações → Movimentos → Documento de Entrada
        → diálogo de sessão → Confirmar.
        """
        if self._aberta:
            return True
        self._log("abrir_rotina")
        click_dom = getattr(self.surface, "click_dom", None) if self.surface else None
        contar = getattr(self.surface, "contar_dom", None) if self.surface else None
        fill_dom = getattr(self.surface, "fill_dom", None) if self.surface else None
        sleep = getattr(self.surface, "sleep", None) if self.surface else None

        def _aguardar(seg: float) -> None:
            if self.simulado or self.surface is None:
                return
            if sleep:
                sleep(seg)
            else:
                self._sleep()

        abriu = False
        if not self.simulado and click_dom and contar:
            try:
                # Espera home do ERP (menu lateral) antes de navegar.
                import time

                deadline = time.time() + AGUARDAR_TELA_S
                while time.time() < deadline and int(contar("text=Atualizações") or 0) <= 0:
                    _aguardar(0.5)
                if int(contar("text=Atualizações") or 0) > 0:
                    click_dom("text=Atualizações")
                    self._log("click_dom:Atualizações")
                    _aguardar(1.2)
                if int(contar("text=Movimentos") or 0) > 0:
                    click_dom("text=Movimentos")
                    self._log("click_dom:Movimentos")
                    _aguardar(1.2)
                for sel in (
                    "text=Documento de Entrada",
                    "text=/Documento de Entrada/i",
                    "text=/Documento/",
                ):
                    if int(contar(sel) or 0) <= 0:
                        continue
                    click_dom(sel)
                    self._log(f"click_dom_menu:{sel}")
                    abriu = True
                    _aguardar(1.5)
                    break
            except Exception as e:
                self._log(f"abrir_rotina_menu_falhou:{type(e).__name__}")

        if not abriu:
            # Fallback legado: Pesquisar + MATA103 (simulado / outros ambientes).
            locate = getattr(self.surface, "locate_center", None) if self.surface else None
            if not self.simulado and click_dom:
                try:
                    click_dom('input[placeholder="Pesquisar"]')
                    self._log("click_dom_pesquisar:fallback")
                except Exception:
                    pass
            elif not self._click_template("campo-pesquisar.png", timeout_s=AGUARDAR_TELA_S):
                if locate:
                    try:
                        centro = locate("mata103/campo-pesquisar.png", confidence=0.72)
                    except Exception:
                        centro = None
                    if centro and self.surface is not None:
                        self.surface.click(centro[0], centro[1])
            self._press("control+a")
            self._press("backspace")
            self._type(ROTINA)
            self._sleep()
            self._press("down")
            self._press("enter")
            self._press("enter")
            _aguardar(2.0)

        # Diálogo de sessão Protheus (Grupo/Filial/Ambiente) → Confirmar.
        # Lab FSB (2026-08-19): campos são canvas (fill_dom costuma falhar).
        # Foco inicial = Data base; clicar o input Filial (~580,318) antes de
        # digitar. Ctrl+A no campo focado apaga a data e o Confirmar recusa.
        if not self.simulado and click_dom and contar:
            fil = (filial_codigo or "").strip()
            if fil:
                preenchida = False
                if fill_dom:
                    for sel, indice in (
                        ('input[name*="Filial" i]', 0),
                        ('input[placeholder*="Filial" i]', 0),
                        ("po-input:has-text('Filial') input", 0),
                        ("label:has-text('Filial') ~ * input", 0),
                        # Fallback: 3º input do diálogo (Data, Grupo, Filial…).
                        ("po-input input", 2),
                    ):
                        try:
                            if int(contar(sel) or 0) <= indice:
                                continue
                            fill_dom(sel, fil, indice=indice)
                            self._log(f"fill_dom_filial:{sel}[{indice}]={fil}")
                            preenchida = True
                            _aguardar(0.5)
                            break
                        except Exception:
                            continue
                if not preenchida:
                    # fill_dom falhou (canvas). Tab×2 a partir da Data base.
                    self._preencher_filial_dialogo_teclado(fil)
                    self._evidencia("mata103_sessao_filial")
            for tentativa in range(2):
                confirmou = False
                for sel in (
                    "button:has-text('Confirmar')",
                    "po-button:has-text('Confirmar')",
                ):
                    try:
                        if int(contar(sel) or 0) <= 0:
                            continue
                        click_dom(sel)
                        self._log(f"click_dom_confirmar_sessao:{sel}")
                        confirmou = True
                        break
                    except Exception as e:
                        self._log(f"confirmar_sessao_falhou:{type(e).__name__}")
                if not confirmou:
                    break
                # Canvas SmartClient demora a pintar após o diálogo.
                _aguardar(AGUARDAR_TELA_S)
                # Sessão AdvPL: título do diálogo (não o botão Visualizar da home).
                ainda = int(
                    contar('[title*="TOTVS Linha Protheus" i]') or 0
                ) > 0 or int(contar('[caption*="Papel de Trabalho" i]') or 0) > 0
                if not ainda:
                    break
                self._log(f"sessao_ainda_aberta:{tentativa + 1}")

        # Só clica no título da rotina se o match for no topo (evita falso positivo).
        pos_titulo = self._locate("mata103/tela-documento-entrada.png", confidence=0.9)
        if pos_titulo and pos_titulo[1] < 80:
            self._click_template("tela-documento-entrada.png", timeout_s=AGUARDAR_TELA_S)
        else:
            self._log("skip_tela_documento_entrada:match_invalido")
        # Lab FSB: após abrir pode surgir Parametros; o filtro F12 auto-aberto
        # é reaproveitado em pesquisar() (não cancelar — F12 depois abre Parametros).
        self._confirmar_parametros(aguardar_s=max(self.settle_s * 2.0, 2.0))
        self._aberta = True
        return True

    def preparar_troca_filial(self, filial_codigo: str = "") -> None:
        """Força reabrir MATA103 na próxima NF (nova filial de sessão)."""
        self._aberta = False
        self._log(f"preparar_troca_filial:{filial_codigo}")

    def _click_dom_primeiro(self, seletores: tuple[str, ...], *, log_tag: str) -> bool:
        if self.simulado or self.surface is None:
            return False
        click_dom = getattr(self.surface, "click_dom", None)
        contar = getattr(self.surface, "contar_dom", None)
        if not click_dom or not contar:
            return False
        for sel in seletores:
            try:
                if int(contar(sel) or 0) <= 0:
                    continue
                click_dom(sel)
                self._log(f"{log_tag}:{sel}")
                self._sleep()
                return True
            except Exception:
                continue
        return False

    def _locate(self, rel: str, *, confidence: float = 0.8) -> tuple[int, int] | None:
        if self.simulado or self.surface is None:
            return None
        locate = getattr(self.surface, "locate_center", None)
        if not locate:
            return None
        try:
            return locate(rel, confidence=confidence)
        except Exception:
            return None

    def _tem_dialogo_parametros(self) -> bool:
        """True só se o botão OK de Parametros estiver visível (evita falso positivo)."""
        if self.simulado or self.surface is None:
            return False
        if self._locate("mata103/btn-parametros-ok.png", confidence=0.88):
            return True
        contar = getattr(self.surface, "contar_dom", None)
        if contar:
            try:
                # Exige título + botão OK no DOM (canvas às vezes espelha botões).
                if int(contar("text=/^Parametros$/i") or 0) > 0 and int(
                    contar("button:has-text('OK')") or 0
                ) > 0:
                    return True
            except Exception:
                pass
        return False

    def _tem_filtro_perguntas(self) -> bool:
        if self._tem_dialogo_parametros():
            return False
        return bool(
            self._locate("mata103/btn-filtro-confirmar.png", confidence=0.85)
            or self._locate("mata103/campo-filtro-numero.png", confidence=0.9)
        )

    def _confirmar_parametros(self, *, aguardar_s: float = 0.0) -> bool:
        """Confirma o diálogo «Parametros» da rotina (botão OK)."""
        if self.simulado or self.surface is None:
            return False
        sleep = getattr(self.surface, "sleep", None)
        if aguardar_s > 0 and sleep:
            sleep(aguardar_s)
        for _ in range(3):
            if not self._tem_dialogo_parametros():
                return False
            # Preferir template canvas: click_dom em «OK» às vezes não fecha o diálogo.
            if self._click_template("btn-parametros-ok.png", timeout_s=2.5):
                if sleep:
                    sleep(max(self.settle_s * 2.0, 2.0))
                if not self._tem_dialogo_parametros():
                    return True
            if self._click_dom_primeiro(
                (
                    "button:has-text('OK')",
                    "po-button:has-text('OK')",
                ),
                log_tag="click_dom_parametros_ok",
            ):
                if sleep:
                    sleep(max(self.settle_s * 2.0, 2.0))
                if not self._tem_dialogo_parametros():
                    return True
            if sleep:
                sleep(0.8)
        return False

    def _cancelar_filtro_perguntas(self) -> None:
        """Fecha «Filtro através de perguntas» residual (Esc / Cancelar)."""
        if self.simulado or self.surface is None:
            return
        if not self._tem_filtro_perguntas():
            return
        if self._click_template("btn-filtro-cancelar.png", timeout_s=2.0):
            self._log("cancelar_filtro_perguntas:template")
            return
        self._press("escape")
        self._sleep()
        self._log("cancelar_filtro_perguntas:escape")

    def _fechar_gerenciador_filtros(self) -> bool:
        """Fecha o «Gerenciador de Filtros» (UI diferente do F12)."""
        contar = getattr(self.surface, "contar_dom", None) if self.surface else None
        if not contar:
            return False
        try:
            if int(contar("text=/Gerenciador de Filtros/i") or 0) <= 0:
                return False
        except Exception:
            return False
        return self._click_dom_primeiro(
            (
                "button:has-text('Cancelar')",
                "po-button:has-text('Cancelar')",
                "text=Cancelar",
            ),
            log_tag="fechar_gerenciador_filtros",
        )

    def _aplicar_gerenciador_filtros(self) -> bool:
        """Aplica filtro parametrizado já definido via perguntas F12."""
        return self._click_dom_primeiro(
            (
                "button:has-text('Aplicar filtros selecionados')",
                "po-button:has-text('Aplicar filtros selecionados')",
                "text=/Aplicar filtros/i",
            ),
            log_tag="aplicar_gerenciador_filtros",
        )

    def _remover_filtros_browse(self) -> bool:
        """Clica «Remover» se o browse tiver filtros aplicados."""
        contar = getattr(self.surface, "contar_dom", None) if self.surface else None
        if contar:
            try:
                if int(contar("text=/filtros aplicados/i") or 0) <= 0:
                    return False
            except Exception:
                return False
        return self._click_dom_primeiro(
            (
                "a:has-text('Remover')",
                "button:has-text('Remover')",
                "text=Remover",
            ),
            log_tag="click_dom_remover_filtros",
        )

    def _aguardar_browse_sem_filtro(self) -> None:
        """Depois de Remover, espera o browse largar o filtro antes do próximo F12."""
        if self.simulado or self.surface is None:
            return
        import time

        sleep = getattr(self.surface, "sleep", None)
        deadline = time.time() + AGUARDAR_TELA_S
        while time.time() < deadline:
            if self._contar_dom("text=/filtros aplicados/i") <= 0:
                if sleep:
                    sleep(max(self.settle_s, 0.8))
                self._log("pesquisar:browse_estavel")
                return
            if sleep:
                sleep(0.4)
        self._log("pesquisar:browse_timeout_filtros")

    def _focar_campo_filtro_numero(self) -> bool:
        """Garante foco no 1º campo do filtro (canvas exige clique)."""
        pos = self._locate("mata103/campo-filtro-numero.png", confidence=0.9)
        click = getattr(self.surface, "click", None) if self.surface else None
        if pos and pos[1] >= 200 and click:
            # Rótulo «Numero Igual a» → clica no campo à direita.
            click(pos[0] + 140, pos[1])
            self._log(f"click_filtro_numero:@({pos[0] + 140},{pos[1]})")
            self._sleep()
            return True
        if self._click_template(
            "campo-filtro-numero.png", timeout_s=2.0, offset_x=140, offset_y=0
        ):
            return True
        if click:
            click(620, 270)
            self._log("click_coords_filtro_numero:620,270")
            self._sleep()
            return True
        return False

    def _confirmar_filtro_perguntas(self) -> bool:
        """Clica Confirmar do filtro (nunca Cancelar — x maior no lab)."""
        click = getattr(self.surface, "click", None) if self.surface else None
        # 1) Âncora estável no rótulo Numero (Confirmar ~ +255x / +257y).
        pos_num = self._locate("mata103/campo-filtro-numero.png", confidence=0.88)
        if pos_num and click:
            x, y = pos_num[0] + 255, pos_num[1] + 257
            click(x, y)
            self._log(f"click_filtro_confirmar_rel:@({x},{y})")
            self._sleep()
            return True
        # 2) Template — rejeita match à direita (Cancelar ~x≥840 no 1280).
        pos = self._locate("mata103/btn-filtro-confirmar.png", confidence=0.92)
        if pos and click and pos[0] < 820:
            click(pos[0], pos[1])
            self._log(f"click_filtro_confirmar_tpl:@({pos[0]},{pos[1]})")
            self._sleep()
            return True
        self._press("enter")
        self._log("click_filtro_confirmar:enter")
        return False

    def _aguardar_filtro_perguntas(self, *, timeout_s: float | None = None) -> bool:
        if timeout_s is None:
            timeout_s = AGUARDAR_TELA_S
        if self.simulado or self.surface is None:
            return True
        sleep = getattr(self.surface, "sleep", None)
        import time

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._tem_filtro_perguntas():
                return True
            if sleep:
                sleep(0.4)
        return False

    def _dismiss_help_dialogs(self) -> None:
        """Fecha diálogos de ajuda/erro comuns (ex.: ARQVAZIO, CTBBLOQ, A103NATURE)."""
        contar = getattr(self.surface, "contar_dom", None) if self.surface else None
        if contar:
            try:
                help_open = int(contar("text=/Help:/i") or 0) > 0 and int(
                    contar("button:has-text('Fechar')") or 0
                ) > 0
                if help_open:
                    self._evidencia("mata103_help")
                    if int(contar("text=/A103NATURE/i") or 0) > 0:
                        self._log("help_codigo:A103NATURE")
                    if int(contar("text=/A100VALDUP/i") or 0) > 0:
                        self._log("help_codigo:A100VALDUP")
            except Exception:
                pass
        self._click_dom_primeiro(
            (
                "button:has-text('Fechar')",
                "po-button:has-text('Fechar')",
            ),
            log_tag="dismiss_dialog",
        )

    def _contar_dom(self, seletor: str) -> int:
        if self.surface is None:
            return 0
        contar = getattr(self.surface, "contar_dom", None)
        if not contar:
            return 0
        try:
            return int(contar(seletor) or 0)
        except Exception:
            return 0

    def _tem_overlay_classificar(self) -> bool:
        """True se modal Informações da Natureza ou Help estiver aberto."""
        if self.surface is None:
            return False
        seletores = (
            "text=/Informações da Natureza/i",
            "text=/Informacoes da Natureza/i",
            "text=/indica calculo para/i",
            "text=/indica cálculo para/i",
            "text=/Help:/i",
        )
        return any(self._contar_dom(sel) > 0 for sel in seletores)

    def _tem_help_a100valdup(self) -> bool:
        if self.surface is None:
            return False
        return (
            self._contar_dom("text=/A100VALDUP/i") > 0
            or self._contar_dom("text=/somatória dos títulos/i") > 0
            or self._contar_dom("text=/somatoria dos titulos/i") > 0
            or self._contar_dom("text=/nao confere com o total da nota/i") > 0
        )

    def _click_fechar_overlay(self) -> bool:
        """Clica Fechar mesmo em modo real com surface fake (testes)."""
        if self.surface is None:
            return False
        click_dom = getattr(self.surface, "click_dom", None)
        if not click_dom:
            return False
        for sel in ("button:has-text('Fechar')", "po-button:has-text('Fechar')"):
            if self._contar_dom(sel) <= 0 and self._contar_dom("text=/Fechar/i") <= 0:
                # Surface de teste pode só responder a substring 'fechar'.
                if "fechar" not in sel.lower():
                    continue
            try:
                if self._contar_dom(sel) > 0 or self._tem_overlay_classificar():
                    click_dom(sel)
                    self._log(f"dismiss_dialog:{sel}")
                    self._sleep()
                    return True
            except Exception:
                continue
        # Fallback amplo para surfaces de teste.
        try:
            if self._tem_overlay_classificar():
                click_dom("button:has-text('Fechar')")
                self._log("dismiss_dialog:button:has-text('Fechar')")
                self._sleep()
                return True
        except Exception:
            pass
        return False

    def _fechar_info_natureza(self) -> bool:
        """Fecha 'Informações da Natureza' / Help após Natureza. False se persistir."""
        if self.surface is None:
            self._log("natureza:info_ok")
            return True
        if not self._tem_overlay_classificar():
            self._log("natureza:info_ok")
            return True
        self._evidencia("mata103_natureza_info")
        self._log("natureza:info_detectada")
        for _ in range(3):
            if not self._tem_overlay_classificar():
                break
            self._click_fechar_overlay()
            self._sleep()
        if self._tem_overlay_classificar():
            self._log("natureza:info_bloqueada")
            self._evidencia("mata103_natureza_info_bloqueada")
            return False
        self._log("natureza:info_fechada")
        return True

    def _focar_vencimento(self) -> None:
        """Refoca o campo vencimento após o modal Natureza.

        Sem clique/Tab o ERP mantém o default (último dia do mês). Template
        opcional ``campo-vencimento.png`` (offset +35, igual à Natureza);
        fallback = Natureza já calibrada + Tab.
        """
        if self.simulado or self.surface is None:
            self._log("duplicatas:venc_foco")
            return
        click = getattr(self.surface, "click", None)
        pos_venc = self._locate("mata103/campo-vencimento.png", confidence=0.85)
        if pos_venc and click:
            x, y = pos_venc[0] + 35, pos_venc[1]
            click(x, y, clicks=2)
            self._log(f"click_vencimento_dbl:@({x},{y})")
            self._log("duplicatas:venc_foco")
            self._sleep()
            return
        pos_nat = self._locate("mata103/campo-natureza.png", confidence=0.85)
        if pos_nat and click:
            x, y = pos_nat[0] + 35, pos_nat[1]
            click(x, y, clicks=2)
            self._press("tab")
            self._log("duplicatas:venc_foco_via_natureza_tab")
            self._sleep()
            return
        if click:
            click(115, 635, clicks=2)
            self._press("tab")
            self._log("duplicatas:venc_foco_via_natureza_coords_tab")
            self._sleep()
            return
        self._log("duplicatas:venc_foco_teclado")

    def _motivo_help_bloqueio(self) -> str | None:
        """Detecta help de negócio (ex.: calendário contábil bloqueado)."""
        if self.simulado or self.surface is None:
            return None
        contar = getattr(self.surface, "contar_dom", None)
        if not contar:
            return None
        try:
            if int(contar("text=/Calendário Contábil Bloqueado/i") or 0) > 0:
                return "Interno - Calendário contábil bloqueado (CTBBLOQ)"
            if int(contar("text=/CTBBLOQ/i") or 0) > 0:
                return "Interno - Help CTBBLOQ"
        except Exception:
            return None
        return None

    def _type_campo(self, texto: str) -> None:
        """Substitui o valor do campo focado (Ctrl+A + texto)."""
        self._press("control+a")
        self._type(texto)

    def pesquisar(
        self,
        *,
        filial_codigo: str,
        numero_nf: str,
        codigo_fornecedor: str,
        encontrada: bool | None = None,
    ) -> bool:
        """Aplica filtros via F12 «Filtro através de perguntas».

        Número e Fornecedor por clique. Depois do Fornecedor o SX1 foca
        Filial sozinho — Tab/clique extra tira o foco e deixa residual SX1.
        """
        self._falha_filtro = None
        self._log(
            f"pesquisar:filial={filial_codigo}|nf={numero_nf}|forn={codigo_fornecedor}"
        )
        self._dismiss_help_dialogs()
        self._fechar_gerenciador_filtros()
        self._confirmar_parametros()
        # Reaproveita «Filtro através de perguntas» se já estiver aberto (auto ao abrir).
        # Não cancelar: um F12 posterior nesta build abre Parametros, não o filtro.
        if not self._tem_filtro_perguntas():
            if self._remover_filtros_browse():
                self._aguardar_browse_sem_filtro()
            for tentativa in range(2):
                if self._tem_dialogo_parametros():
                    self._confirmar_parametros()
                self._press("f12")
                self._sleep()
                if self._tem_dialogo_parametros():
                    # F12 abriu Parametros — confirma e tenta de novo só 1x.
                    self._confirmar_parametros()
                    if self._aguardar_filtro_perguntas():
                        break
                    self._log(f"pesquisar:f12_viu_parametros:{tentativa + 1}")
                    continue
                if self._aguardar_filtro_perguntas():
                    break
                self._log(f"pesquisar:filtro_retry:{tentativa + 1}")
            else:
                self._log("pesquisar:filtro_nao_abriu")
                if self.simulado:
                    return True if encontrada is None else bool(encontrada)
                self._falha_filtro = MOTIVOS.FILTRO_MATA103_NAO_CARREGADO
                return False
        # Normaliza DOC a 9 dígitos quando numérico (padrão SF1/F1_DOC).
        doc = (numero_nf or "").strip()
        dig = "".join(ch for ch in doc if ch.isdigit())
        if dig:
            doc = dig.zfill(9)[-9:]
        forn = (codigo_fornecedor or "").strip()
        fil = (filial_codigo or "").strip()
        pos_num = self._locate("mata103/campo-filtro-numero.png", confidence=0.88)
        click = getattr(self.surface, "click", None) if self.surface else None
        if pos_num and click and pos_num[1] >= 200:
            x0, y0 = pos_num[0] + _FILTRO_DX_INPUT, pos_num[1]
            click(x0, y0 + _FILTRO_DY_NUMERO)
            self._log(f"click_filtro_numero:@({x0},{y0 + _FILTRO_DY_NUMERO})")
            self._sleep()
            self._type_campo(doc)
            click(x0, y0 + _FILTRO_DY_FORNECEDOR)
            self._log(f"click_filtro_fornecedor:@({x0},{y0 + _FILTRO_DY_FORNECEDOR})")
            self._sleep()
            self._type_campo(forn)
            self._preencher_filial_filtro_foco_erp(fil)
            self._evidencia("mata103_filtro_preenchido")
        else:
            if not self._focar_campo_filtro_numero():
                self._log("pesquisar:sem_foco_numero")
            self._type_campo(doc)
            self._press("down")
            self._type_campo(forn)
            self._preencher_filial_filtro_foco_erp(fil)
            self._evidencia("mata103_filtro_preenchido")
        self._confirmar_filtro_perguntas()
        sleep = getattr(self.surface, "sleep", None) if self.surface else None
        if sleep:
            sleep(max(self.settle_s * 3.0, 3.5))
        self._confirmar_parametros()
        self._dismiss_help_dialogs()
        if sleep:
            sleep(max(self.settle_s * 1.5, 1.5))
        if self.simulado:
            return True if encontrada is None else bool(encontrada)
        if self._tem_filtro_perguntas():
            self._log("pesquisar:filtro_ainda_aberto")
            self._evidencia("mata103_pesquisar_filtro_aberto")
            return False
        if self._tem_dialogo_parametros():
            self._log("pesquisar:ainda_parametros")
            self._evidencia("mata103_pesquisar_parametros")
            return False
        contar = getattr(self.surface, "contar_dom", None) if self.surface else None
        if contar:
            try:
                # Preferir evidência positiva da NF; «Sem registros» só se o DOC não aparecer.
                doc_ok = (not dig) or int(contar(f"text=/{doc}/") or 0) > 0
                forn_ok = (not forn) or int(contar(f"text=/{forn}/i") or 0) > 0
                if doc_ok and forn_ok:
                    self._log("pesquisar:linha_ok")
                    return True
                if int(contar("text=/Sem registros/i") or 0) > 0:
                    self._log("pesquisar:sem_registros")
                    self._evidencia("mata103_pesquisar_sem_registros")
                    return False
                if dig and not doc_ok:
                    self._log(f"pesquisar:doc_nao_visivel:{doc}")
                    self._evidencia("mata103_pesquisar_doc_nao_visivel")
                    return False
                if forn and not forn_ok:
                    self._log(f"pesquisar:forn_nao_visivel:{forn}")
                    self._evidencia("mata103_pesquisar_forn_nao_visivel")
                    return False
            except Exception:
                pass
        return True

    def _formulario_classificacao_aberto(self) -> bool:
        if self.simulado or self.surface is None:
            return True
        contar = getattr(self.surface, "contar_dom", None)
        if not contar:
            return False
        try:
            # Exige diálogo AdvPL aberto (evita falso positivo do painel Detalhes).
            if int(contar('wa-dialog[opened][title*="CLASSIFICAR" i]') or 0) > 0:
                return True
            if int(contar('wa-dialog[opened][title*="Classificar" i]') or 0) > 0:
                return True
            # Alguns builds usam o mesmo shell com caption.
            if int(contar('wa-dialog[opened]') or 0) > 0 and int(
                contar("text=/Duplicatas/i") or 0
            ) > 0:
                return True
        except Exception:
            return False
        return False

    def _fechar_visualizar_se_aberto(self) -> None:
        """Fecha diálogo «Documento de Entrada - VISUALIZAR» se estiver aberto.

        Não usar text=Visualizar — casa o botão da toolbar e dá Escape à toa.
        """
        contar = getattr(self.surface, "contar_dom", None) if self.surface else None
        if not contar:
            return
        try:
            aberto = int(
                contar('[title*="Documento de Entrada - VISUALIZAR" i]') or 0
            ) > 0 or int(
                contar('[caption*="Documento de Entrada - VISUALIZAR" i]') or 0
            ) > 0
        except Exception:
            aberto = False
        if not aberto:
            return
        self._press("escape")
        self._sleep()
        self._log("fechar_visualizar:escape")

    def acionar_classificar(self) -> bool:
        self._dismiss_help_dialogs()
        self._fechar_visualizar_se_aberto()
        click_dom = getattr(self.surface, "click_dom", None) if self.surface else None
        contar = getattr(self.surface, "contar_dom", None) if self.surface else None
        sleep = getattr(self.surface, "sleep", None) if self.surface else None

        def _aguardar_form() -> bool:
            if self.simulado or self.surface is None:
                return True
            import time

            deadline = time.time() + AGUARDAR_TELA_S
            while time.time() < deadline:
                self._confirmar_parametros()
                self._dismiss_help_dialogs()
                if self._formulario_classificacao_aberto():
                    return True
                if sleep:
                    sleep(0.4)
            return self._formulario_classificacao_aberto()

        # 1) Foca Classificar e confirma com Space/Enter (clique só foca o botão PO).
        if not self.simulado and click_dom and contar:
            for sel in (
                "button:has-text('Classificar')",
                "po-button:has-text('Classificar')",
            ):
                try:
                    if int(contar(sel) or 0) <= 0:
                        continue
                    try:
                        click_dom(sel, force=True)
                    except TypeError:
                        click_dom(sel)
                    self._log(f"click_dom_classificar:{sel}")
                    self._press("space")
                    if _aguardar_form():
                        return True
                    self._press("enter")
                    if _aguardar_form():
                        return True
                except Exception as e:
                    self._log(f"click_dom_classificar_falhou:{type(e).__name__}")
                    continue
        # 2) Template + Space
        if self._click_template("btn-classificar.png", timeout_s=AGUARDAR_TELA_S):
            self._press("space")
            if _aguardar_form():
                return True
        # 3) Alt+C
        self._press("alt+c")
        if _aguardar_form():
            return True
        self._log("acionar_classificar:formulario_nao_aberto")
        if contar:
            try:
                self._log(
                    "dom_pos_classificar:"
                    f"dlg={contar('wa-dialog[opened]')}"
                    f" duplicatas={contar('text=/Duplicatas/i')}"
                    f" help={contar('text=/Help:/i')}"
                    f" vis={contar('[title*=\"VISUALIZAR\" i]')}"
                )
            except Exception:
                pass
        self._evidencia("mata103_classificar_falhou")
        return False

    def preencher_cod_serv_iss(self, codigo: str) -> bool:
        """Preenche Cod.Serv.ISS com o item já normalizado (``xx.xx``).

        O template do campo é o caminho estável. Sem o PNG, 159 setas à direita
        a partir da área de navegação — só nesse caso.
        """
        valor = (codigo or "").strip()
        if not valor:
            self._log("cod_serv_iss:ausente")
            return False
        self._log(f"cod_serv_iss:{valor}")
        tem_template = self._template("campo-cod-serv-iss.png").is_file()
        if self.simulado or tem_template:
            if self._click_template(
                "campo-cod-serv-iss.png", timeout_s=4.0, offset_x=35
            ):
                self._type_campo(valor)
                self._press("tab")
                return True
        self._log("cod_serv_iss:setas")
        for _ in range(159):
            self._press("ArrowRight")
        self._type_campo(valor)
        self._press("tab")
        return True

    def preencher_duplicatas(self, *, natureza: str, data_vencimento: str) -> bool:
        self._log(f"duplicatas:natureza={natureza}|venc={data_vencimento}")
        if not self._click_template(
            "aba-duplicatas.png", timeout_s=5.0, confidence=0.85
        ):
            # Fallback: algumas builds usam Ctrl+Page para abas — lab redefine.
            self._press("ctrl+pagedown")
        self._sleep()
        click = getattr(self.surface, "click", None) if self.surface else None
        # NÃO clicar na grade de parcelas: edita «Parcela» e rouba o teclado.
        # Lab 1280x720: input Natureza ~x=70..160 y≈630 (offset +35 do rótulo;
        # +110 caía no lookup/fora e a digitação não entrava).
        pos_nat = self._locate("mata103/campo-natureza.png", confidence=0.85)
        if pos_nat and click:
            x, y = pos_nat[0] + 35, pos_nat[1]
            click(x, y, clicks=2)
            self._log(f"click_natureza_dbl:@({x},{y})")
            self._sleep()
        elif click:
            click(115, 635, clicks=2)
            self._log("click_natureza_coords_dbl:115,635")
            self._sleep()
        self._type_campo(natureza)
        self._press("tab")
        self._sleep()
        # Natureza com retenção abre «Informações da Natureza» — fechar antes do vencimento.
        if not self._fechar_info_natureza():
            return False
        # Modal rouba o foco; sem refoco o Protheus mantém o default (fim do mês).
        self._focar_vencimento()
        # Vencimento: digitar data do data-plane (PDF FSB — validar/ajustar na UI).
        venc_ui = self._data_ui(data_vencimento)
        if venc_ui:
            self._type_campo(venc_ui)
            self._press("tab")
            self._log(f"duplicatas:venc_digitado={venc_ui}")
        else:
            self._log("duplicatas:venc_ausente")
        return True

    def _confirmar_dialogos_pos_salvar(self) -> None:
        """Confirma diálogos de contabilização / pergunta após Salvar."""
        # Ordem: Sim/Confirmar antes de OK genérico (Parametros).
        for _ in range(4):
            if self._click_dom_primeiro(
                (
                    "button:has-text('Sim')",
                    "po-button:has-text('Sim')",
                    "button:has-text('Confirmar')",
                    "po-button:has-text('Confirmar')",
                    "button:has-text('OK')",
                    "po-button:has-text('OK')",
                ),
                log_tag="pos_salvar",
            ):
                self._sleep()
                continue
            break
        self._dismiss_help_dialogs()

    @staticmethod
    def _data_ui(iso_ou_br: str | None) -> str:
        """Converte YYYY-MM-DD (ou já BR) para DD/MM/YYYY no Protheus."""
        raw = (iso_ou_br or "").strip()
        if not raw:
            return ""
        if "/" in raw and len(raw) >= 8:
            return raw
        partes = raw.split("-")
        if len(partes) == 3 and len(partes[0]) == 4:
            return f"{partes[2]}/{partes[1]}/{partes[0]}"
        return raw

    def _selecionar_linha_imposto(self, rotulo: str) -> None:
        """Foca a linha do imposto na grade (fallback teclado; lab recalibra)."""
        self._log(f"imposto:selecionar:{rotulo}")
        self._type(rotulo)
        self._press("enter")
        self._sleep()

    def _preencher_cobranca_iss(self, item: ItemCheckpoint) -> None:
        """Dados de cobrança ISS: código do fornecedor + data pagamento (= emissão)."""
        forn = (item.codigo_fornecedor or "").strip()
        data = self._data_ui(item.data_emissao_nf)
        self._log(f"iss:cobranca:forn={forn}|data={data or '-'}")
        if forn:
            self._type_campo(forn)
            self._press("tab")
        if data:
            self._log(f"iss:cobranca:data={data}")
            self._type_campo(data)
            self._press("tab")

    def _preencher_retencao_imposto(
        self, *, rotulo: str, codigo_retencao: str, tag: str
    ) -> None:
        self._selecionar_linha_imposto(rotulo)
        self._log(f"{tag}:dirf=S retencao={codigo_retencao}")
        self._type("S")  # Gera Dirf
        self._press("tab")
        self._type(codigo_retencao)
        self._press("tab")

    def preencher_impostos(self, item: ItemCheckpoint) -> bool:
        """Aba Impostos (CR FSB): sempre abrir; ISS Recolhe Sim se zerado."""
        self._log(
            f"impostos:iss={item.tem_iss_a_recolher}|ir={item.tem_irrf}|pcc={item.tem_pcc}"
        )
        # Não digitar impostos com modal/Help ainda aberto (lab: digitava na Duplicatas).
        if not self._fechar_info_natureza():
            self._log("impostos:bloqueado_overlay")
            return False
        # Sempre abrir a aba (mesmo sem retenção): Recolhe ISS=Sim é obrigatório
        # quando a NF não traz ISS a recolher (PDF FSB — subprocesso Classificar).
        pos_imp = self._locate("mata103/aba-impostos.png", confidence=0.9)
        click = getattr(self.surface, "click", None) if self.surface else None
        if pos_imp and click and pos_imp[0] > 400:
            click(pos_imp[0], pos_imp[1])
            self._log(f"click_aba_impostos:@({pos_imp[0]},{pos_imp[1]})")
            self._sleep()
        elif not self._click_template(
            "aba-impostos.png", timeout_s=5.0, confidence=0.9
        ):
            self._press("ctrl+pagedown")
            self._sleep()
        if self._tem_overlay_classificar():
            self._log("impostos:bloqueado_overlay")
            self._evidencia("mata103_impostos_bloqueado")
            return False
        self._log("impostos:aba_pronta")
        self._evidencia("mata103_impostos")
        if click:
            click(420, 620)
            self._log("click_campo_impostos:420,620")
            self._sleep()

        # ISS — Recolhe Não se houver valor a recolher; Sim se zerado / não retido.
        # Cobrança (forn + data NF) só quando Recolhe=Não (PDF FSB).
        self._selecionar_linha_imposto("ISS")
        if item.tem_iss_a_recolher:
            self._log("iss:recolhe=Nao")
            self._type("N")
            self._press("tab")
            self._preencher_cobranca_iss(item)
        else:
            self._log("iss:recolhe=Sim")
            self._type("S")
            self._press("tab")

        if item.tem_irrf:
            self._preencher_retencao_imposto(
                rotulo="IRR", codigo_retencao=COD_RETENCAO_IR, tag="ir"
            )

        if item.tem_pcc:
            for imposto in ("PIS", "COFINS", "CSLL"):
                self._preencher_retencao_imposto(
                    rotulo=imposto, codigo_retencao=COD_RETENCAO_PCC, tag=f"pcc:{imposto}"
                )
        return True

    def _tem_tela_contabilizacao(self) -> bool:
        if self._locate("mata103/tela-contabilizacao.png", confidence=0.85):
            return True
        return any(
            self._contar_dom(sel) > 0
            for sel in (
                "text=/Débitos e Créditos/i",
                "text=/Debitos e Creditos/i",
                "text=/Contabilização/i",
                "text=/Contabilizacao/i",
            )
        )

    def _aguardar_tela_contabilizacao(self, *, presente: bool) -> bool:
        if self.simulado or self.surface is None:
            return True
        import time

        sleep = getattr(self.surface, "sleep", None)
        deadline = time.time() + AGUARDAR_TELA_S
        while time.time() < deadline:
            if self._tem_tela_contabilizacao() == presente:
                return True
            if sleep:
                sleep(0.2)
        return self._tem_tela_contabilizacao() == presente

    def salvar_classificacao(self) -> bool:
        self._log("salvar")
        if self.simulado or self.surface is None:
            # PDF FSB: 1º Salvar classificação + 2º após contabilização.
            self._log("salvar:2")
            return True
        sleep = getattr(self.surface, "sleep", None) if self.surface else None

        if not self._click_template("btn-salvar.png", timeout_s=6.0):
            # Fallback DOM / teclado
            if not self._click_dom_primeiro(
                ("button:has-text('Salvar')", "po-button:has-text('Salvar')"),
                log_tag="click_dom_salvar",
            ):
                self._press("ctrl+s")
        if sleep:
            sleep(max(self.settle_s * 3.0, 3.5))
        self._evidencia("mata103_salvar_apos1")
        # Help de negócio (ex.: A100VALDUP) — não seguir para 2º Salvar às cegas.
        if self._tem_help_a100valdup():
            self._log("salvar:bloqueio:A100VALDUP")
            self._evidencia("mata103_salvar_a100valdup")
            self._dismiss_help_dialogs()
            return False
        self._confirmar_dialogos_pos_salvar()
        if self._tem_help_a100valdup():
            self._log("salvar:bloqueio:A100VALDUP")
            self._evidencia("mata103_salvar_a100valdup")
            self._dismiss_help_dialogs()
            return False

        if self._template("tela-contabilizacao.png").is_file():
            if not self._aguardar_tela_contabilizacao(presente=True):
                self._log("salvar:contabilizacao_nao_abriu")
                self._evidencia("mata103_salvar_sem_contabilizacao")
                return False
        else:
            self._log("salvar:contabilizacao_sem_template")

        # Segunda gravação (contabilização débitos/créditos) — sempre tentar.
        self._log("salvar:2")
        if not self._click_template("btn-salvar.png", timeout_s=4.0):
            if not self._click_dom_primeiro(
                ("button:has-text('Salvar')", "po-button:has-text('Salvar')"),
                log_tag="click_dom_salvar2",
            ):
                self._press("ctrl+s")
        if sleep:
            sleep(max(self.settle_s * 3.0, 3.5))
        self._evidencia("mata103_salvar_apos2")
        self._confirmar_dialogos_pos_salvar()
        if self._template("tela-contabilizacao.png").is_file():
            if not self._aguardar_tela_contabilizacao(presente=False):
                self._log("salvar:contabilizacao_ainda_aberta")
                self._evidencia("mata103_salvar_contabilizacao_aberta")
                return False
            self._log("salvar:contabilizacao_fechou")

        # Aguarda o diálogo CLASSIFICAR fechar.
        if sleep:
            for i in range(12):
                if not self._formulario_classificacao_aberto():
                    self._log("salvar:form_fechou")
                    return True
                self._confirmar_dialogos_pos_salvar()
                sleep(1.0)
                if i == 5:
                    self._evidencia("mata103_salvar_ainda_aberto")
        if self._formulario_classificacao_aberto():
            self._log("salvar:form_ainda_aberto")
            self._evidencia("mata103_salvar_falhou")
            return False
        return True

    def classificar_item(
        self,
        item: ItemCheckpoint,
        *,
        encontrada: bool | None = None,
    ) -> ResultadoUiNf:
        """Executa o fluxo UI completo para um item PRONTO_UI."""
        if not item.natureza_despesa or not item.data_vencimento:
            return ResultadoUiNf(
                False,
                StatusNf.NAO_CLASSIFICADO,
                MOTIVOS.DEPARA_NATUREZA_AUSENTE,
                "campos UI incompletos",
            )
        if not self.abrir_rotina(filial_codigo=FILIAL_HOLDING):
            return ResultadoUiNf(
                False, StatusNf.NAO_CLASSIFICADO, "Interno - Falha ao abrir MATA103"
            )
        if not self.pesquisar(
            filial_codigo=item.filial_codigo,
            numero_nf=item.numero_nf,
            codigo_fornecedor=item.codigo_fornecedor,
            encontrada=encontrada,
        ):
            if self._falha_filtro:
                return ResultadoUiNf(False, StatusNf.PRONTO_UI, self._falha_filtro)
            return ResultadoUiNf(
                False,
                StatusNf.NAO_CLASSIFICADO,
                MOTIVOS.NF_NAO_ENCONTRADA_ERP,
            )
        if not self.acionar_classificar():
            return ResultadoUiNf(
                False,
                StatusNf.NAO_CLASSIFICADO,
                "Interno - Formulário Classificar não abriu",
            )
        bloqueio = self._motivo_help_bloqueio()
        if bloqueio:
            self._dismiss_help_dialogs()
            return ResultadoUiNf(False, StatusNf.NAO_CLASSIFICADO, bloqueio)
        if not self.preencher_cod_serv_iss(item.codigo_servico or ""):
            return ResultadoUiNf(
                False,
                StatusNf.NAO_CLASSIFICADO,
                MOTIVOS.campo_nao_coletado("Cod.Serv.ISS"),
            )
        if not self.preencher_duplicatas(
            natureza=item.natureza_despesa,
            data_vencimento=item.data_vencimento,
        ):
            return ResultadoUiNf(
                False, StatusNf.NAO_CLASSIFICADO, "Interno - Duplicatas falhou"
            )
        if not self.preencher_impostos(item):
            return ResultadoUiNf(
                False, StatusNf.NAO_CLASSIFICADO, "Interno - Impostos falhou"
            )
        if not self.salvar_classificacao():
            return ResultadoUiNf(
                False, StatusNf.NAO_CLASSIFICADO, "Interno - Salvar classificação falhou"
            )
        return ResultadoUiNf(True, StatusNf.CLASSIFICADO, None, "ui_ok")
