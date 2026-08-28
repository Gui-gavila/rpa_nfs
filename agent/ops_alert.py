"""Alerta operacional: screenshot da falha + e-mail SMTP.

Destinado a operação (quem opera o agendamento), não a negócio — integrações de
negócio ficam na especialização do ERP.

Regra invariável: `notify_run_failure` nunca propaga exceção. Ele roda no
`except` do worker; falhar aqui mascararia o erro real da corrida.
"""

from __future__ import annotations

import logging
import os
import smtplib
import traceback
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def resolve_alert_dir(log_dir: Path | None = None) -> Path:
    """Pasta dos PNG de falha UI (05_Screenshots/ANOMES). `log_dir` é legado e ignorado."""
    from agent.jobs.classificar_nf.caminhos import pasta_screenshot_falha

    return pasta_screenshot_falha()


def _gravar_frame(frame: Any, path: Path) -> bool:
    """Grava um frame (np.ndarray BGR) em disco. False se não for possível."""
    try:
        import cv2

        return bool(cv2.imwrite(str(path), frame))
    except Exception:
        pass
    try:
        from PIL import Image

        Image.fromarray(frame[:, :, ::-1]).save(str(path))
        return True
    except Exception as e:
        logger.warning("[ops_alert] não foi possível gravar frame: %s", e)
        return False


def gravar_screenshot_ui(
    *,
    surface: Any = None,
    contexto: str = "erro",
    pasta: str | Path | None = None,
    when: datetime | None = None,
) -> Path | None:
    """Grava PNG da UI em 05_Screenshots/ANOMES. Nunca propaga exceção.

    O nome do ficheiro (stamp + contexto) entra no log para cruzar com a falha.
    """
    from agent.jobs.classificar_nf.caminhos import (
        montar_nome_screenshot,
        pasta_screenshot_falha,
    )

    out_dir = pasta_screenshot_falha(pasta)
    path = out_dir / montar_nome_screenshot(contexto, when=when)
    if surface is None:
        logger.warning("[screenshot] falhou: sem Surface contexto=%s", contexto)
        return None
    try:
        shot = getattr(surface, "screenshot_para", None)
        if callable(shot):
            shot(str(path))
        else:
            frame = surface.capture()
            if frame is None or not _gravar_frame(frame, path):
                logger.warning(
                    "[screenshot] Surface não devolveu frame contexto=%s", contexto
                )
                return None
        logger.info(
            "[screenshot] arquivo=%s pasta=%s contexto=%s",
            path.name,
            out_dir,
            contexto,
        )
        return path
    except Exception as e:
        logger.warning("[screenshot] captura falhou contexto=%s: %s", contexto, e)
        return None


def capture_error_screenshot(
    *,
    surface: Any = None,
    log_dir: Path | None = None,
    prefix: str = "erro",
) -> Path | None:
    """PNG do estado da tela no momento da falha. Destino = 05_Screenshots (não o log)."""
    del log_dir  # legado: PNG não acompanha mais o ficheiro de log
    return gravar_screenshot_ui(surface=surface, contexto=prefix)


def _smtp_configured() -> bool:
    return bool((os.getenv("ALERT_SMTP_HOST") or "").strip())


def _anexar(msg: EmailMessage, path: Path) -> None:
    """Anexa um ficheiro escolhendo o mimetype pelo sufixo."""
    data = path.read_bytes()
    sufixo = path.suffix.lower()
    if sufixo in (".log", ".txt"):
        maintype, subtype = "text", "plain"
    elif sufixo == ".png":
        maintype, subtype = "image", "png"
    else:
        maintype, subtype = "application", "octet-stream"
    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)


def send_ops_alert(
    *,
    subject: str,
    body: str,
    attachments: list[Path] | None = None,
) -> dict[str, Any]:
    """Envia e-mail de operação via SMTP.

    Sem ALERT_SMTP_HOST/TO configurados, devolve `skipped` em vez de falhar:
    alerta é observabilidade opcional, não requisito de execução.
    """
    host = (os.getenv("ALERT_SMTP_HOST") or "").strip()
    if not host:
        logger.warning("[ops_alert] e-mail skip (ALERT_SMTP_HOST vazio)")
        return {"ok": False, "skipped": True, "erro": "ALERT_SMTP_HOST_ausente"}

    mail_to_raw = (os.getenv("ALERT_SMTP_TO") or "").strip()
    if not mail_to_raw:
        logger.warning("[ops_alert] e-mail skip (ALERT_SMTP_TO vazio)")
        return {"ok": False, "skipped": True, "erro": "ALERT_SMTP_TO_ausente"}

    port = int(os.getenv("ALERT_SMTP_PORT", "587"))
    user = (os.getenv("ALERT_SMTP_USER") or "").strip()
    password = os.getenv("ALERT_SMTP_PASSWORD") or ""
    mail_from = (os.getenv("ALERT_SMTP_FROM") or user or "carol-agent@localhost").strip()
    recipients = [x.strip() for x in mail_to_raw.replace(";", ",").split(",") if x.strip()]
    use_tls = (os.getenv("ALERT_SMTP_TLS", "1").strip().lower() in ("1", "true", "yes", "sim"))

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    for att in attachments or []:
        p = Path(att)
        if p.is_file():
            _anexar(msg, p)

    try:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            if use_tls:
                smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        logger.info("[ops_alert] e-mail enviado to=%s subject=%r", recipients, subject)
        return {"ok": True, "skipped": False, "to": recipients}
    except Exception as e:
        logger.error("[ops_alert] e-mail falhou: %s", e)
        return {"ok": False, "skipped": False, "erro": str(e)}


def notify_run_failure(
    *,
    result: dict[str, Any] | None = None,
    exc: BaseException | None = None,
    surface: Any = None,
    log_path: Path | None = None,
    log_dir: Path | None = None,
    titulo: str = "Carol Agent",
) -> dict[str, Any]:
    """Screenshot + e-mail em falha de corrida. Nunca propaga exceção."""
    out: dict[str, Any] = {"screenshot": None, "email": None}
    try:
        shot = capture_error_screenshot(surface=surface, log_dir=log_dir)
        out["screenshot"] = str(shot) if shot else None

        erro = str((result or {}).get("erro") or "")
        if exc is not None:
            erro = f"{type(exc).__name__}: {exc}"

        lines = [
            f"{titulo} — falha na execução agendada.",
            "",
            f"erro: {erro or '(ver passos/log)'}",
            f"log: {log_path or '(n/d)'}",
            f"screenshot: {out['screenshot'] or '(n/d)'}",
            "",
        ]
        if result:
            lines.append("passos:")
            for p in result.get("passos") or []:
                if isinstance(p, dict):
                    detalhe = p.get("detalhe") or p.get("erro") or ""
                    lines.append(f"  - {p.get('passo')}: ok={p.get('ok')} {detalhe}")
            lines.append("")
        if exc is not None:
            lines.append("traceback:")
            lines.append("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))

        attachments = [p for p in (shot, Path(log_path) if log_path else None) if p and Path(p).is_file()]
        subject = f"[{titulo}] FALHA {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        if _smtp_configured():
            out["email"] = send_ops_alert(
                subject=subject, body="\n".join(lines), attachments=attachments
            )
        else:
            out["email"] = {"ok": False, "skipped": True, "erro": "ALERT_SMTP_HOST_ausente"}
            logger.warning(
                "[ops_alert] falha registada sem e-mail; screenshot=%s log=%s",
                out["screenshot"],
                log_path,
            )
    except Exception as e:
        logger.error("[ops_alert] notify_run_failure: %s", e)
        out["erro"] = str(e)
    return out
