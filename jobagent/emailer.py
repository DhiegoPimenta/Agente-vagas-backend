from __future__ import annotations

import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(cfg: dict, html: str) -> str:
    ec = cfg.get("email", {})
    if not ec.get("enabled"):
        return "e-mail desativado (email.enabled=false) - relatorio salvo so em arquivo."

    pw_env = ec.get("smtp_password_env", "JOBAGENT_SMTP_PASSWORD")
    password = os.getenv(pw_env, "")
    if not password:
        return f"variavel {pw_env} vazia - e-mail NAO enviado (relatorio salvo em arquivo)."

    sender = ec.get("from_addr") or ec.get("smtp_user")
    recipients = [x.strip() for x in str(ec.get("to_addr", "")).split(",") if x.strip()]
    if not sender or not recipients:
        return "email.from_addr/to_addr incompletos - e-mail NAO enviado."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{ec.get('subject_prefix', '[Vagas]')} {date.today():%d/%m/%Y}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText("Seu cliente de e-mail nao suporta HTML.", "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(ec["smtp_host"], int(ec.get("smtp_port", 587)), timeout=30) as server:
        server.starttls()
        server.login(ec.get("smtp_user"), password)
        server.sendmail(sender, recipients, msg.as_string())
    return f"e-mail enviado para {', '.join(recipients)}."
