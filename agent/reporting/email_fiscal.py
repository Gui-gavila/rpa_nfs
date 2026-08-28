"""E-mail fiscal do relatório de execução (SMTP de negócio ≠ ALERT_*)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _anexar(msg: EmailMessage, path: Path) -> None:
    data = path.read_bytes()
    sufixo = path.suffix.lower()
    if sufixo == ".csv":
        maintype, subtype = "text", "csv"
    elif sufixo in (".xlsx", ".xlsm"):
        maintype, subtype = (
            "application",
            "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    elif sufixo in (".log", ".txt", ".json"):
        maintype, subtype = "text", "plain"
    else:
        maintype, subtype = "application", "octet-stream"
    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)


def enviar_relatorio_fiscal(
    *,
    subject: str,
    body: str,
    attachments: list[Path] | None = None,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    mail_from: str | None = None,
    mail_to: str | None = None,
    use_tls: bool | None = None,
) -> dict[str, Any]:
    """Envia relatório. Sem REPORT_SMTP_HOST/TO → skipped (não falha a corrida)."""
    from agent import config

    host_ef = (host if host is not None else config.REPORT_SMTP_HOST).strip()
    if not host_ef:
        logger.warning("[email_fiscal] skip (REPORT_SMTP_HOST vazio)")
        return {"ok": False, "skipped": True, "erro": "REPORT_SMTP_HOST_ausente"}

    to_raw = (mail_to if mail_to is not None else config.REPORT_SMTP_TO).strip()
    if not to_raw:
        logger.warning("[email_fiscal] skip (REPORT_SMTP_TO vazio)")
        return {"ok": False, "skipped": True, "erro": "REPORT_SMTP_TO_ausente"}

    port_ef = int(port if port is not None else config.REPORT_SMTP_PORT)
    user_ef = (user if user is not None else config.REPORT_SMTP_USER).strip()
    pass_ef = password if password is not None else config.REPORT_SMTP_PASSWORD
    from_ef = (
        mail_from
        if mail_from is not None
        else (config.REPORT_SMTP_FROM or user_ef or "carol-tezk42@localhost")
    ).strip()
    tls_ef = config.REPORT_SMTP_TLS if use_tls is None else bool(use_tls)
    recipients = [x.strip() for x in to_raw.replace(";", ",").split(",") if x.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_ef
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    for att in attachments or []:
        p = Path(att)
        if p.is_file():
            _anexar(msg, p)

    try:
        with smtplib.SMTP(host_ef, port_ef, timeout=60) as smtp:
            if tls_ef:
                smtp.starttls()
            if user_ef:
                smtp.login(user_ef, pass_ef)
            smtp.send_message(msg)
        logger.info("[email_fiscal] enviado to=%s subject=%r", recipients, subject)
        return {"ok": True, "skipped": False, "to": recipients}
    except Exception as e:
        logger.error("[email_fiscal] falhou: %s", e)
        return {"ok": False, "skipped": False, "erro": str(e)}
