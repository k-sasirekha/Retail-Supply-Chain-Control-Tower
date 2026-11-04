"""Send pending alerts from alert_log by email, one message per run.

Reads SMTP_HOST, SMTP_PORT, ALERT_EMAIL_FROM and ALERT_EMAIL_TO from the environment (.env).
Mail goes to a local MailHog by default, so no real mail account is needed.
If ALERT_EMAIL_TO is not set, nothing is sent and the alerts stay 'pending'.
"""
import logging
import os
import smtplib
from email.message import EmailMessage

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10
MAX_ALERTS_PER_EMAIL = 50


def load_pending(conn: Connection) -> list[dict]:
    """Alerts not yet emailed, critical ones first."""
    rows = conn.execute(
        text(
            "SELECT alert_id, rule_name, severity, message FROM alert_log "
            "WHERE email_status = 'pending' ORDER BY (severity = 'critical') DESC, alert_id"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def build_email(alerts: list[dict], sender: str, recipient: str) -> EmailMessage:
    """Plain-text email listing the alerts."""
    critical = sum(1 for a in alerts if a["severity"] == "critical")
    msg = EmailMessage()
    msg["Subject"] = f"[Control Tower] {len(alerts)} new alert(s), {critical} critical"
    msg["From"] = sender
    msg["To"] = recipient
    lines = [f"{len(alerts)} new alert(s) from the Control Tower:", ""]
    lines += [f"[{a['severity'].upper()}] {a['message']}" for a in alerts]
    lines += ["", "Thresholds are stored in the alert_config table."]
    msg.set_content("\n".join(lines))
    return msg


def send_email(host: str, port: int, msg: EmailMessage) -> bool:
    """Send one message through an SMTP server. Returns True on success."""
    try:
        with smtplib.SMTP(host, port, timeout=TIMEOUT_SECONDS) as server:
            server.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log.error("Email send failed: %s", exc)
        return False


def mark(conn: Connection, alert_ids: list[int], status: str) -> None:
    """Set email_status for the given alerts."""
    conn.execute(
        text("UPDATE alert_log SET email_status = :s WHERE alert_id = ANY(:ids)"),
        {"s": status, "ids": alert_ids},
    )


def send_pending() -> int:
    """Email every pending alert. Returns how many were sent."""
    host = os.getenv("SMTP_HOST", "localhost")
    port = int(os.getenv("SMTP_PORT", "1025"))
    sender = os.getenv("ALERT_EMAIL_FROM", "alerts@control-tower.local")
    recipient = os.getenv("ALERT_EMAIL_TO", "").strip()
    engine = create_engine(config.database_url())
    sent = 0
    with engine.begin() as conn:
        alerts = load_pending(conn)
        if not alerts:
            log.info("No pending alerts.")
            return 0
        if not recipient:
            log.warning("ALERT_EMAIL_TO is not set. %d alerts stay pending.", len(alerts))
            return 0
        for i in range(0, len(alerts), MAX_ALERTS_PER_EMAIL):
            chunk = alerts[i : i + MAX_ALERTS_PER_EMAIL]
            ok = send_email(host, port, build_email(chunk, sender, recipient))
            mark(conn, [a["alert_id"] for a in chunk], "sent" if ok else "failed")
            sent += len(chunk) if ok else 0
    log.info("Emailed %d of %d pending alerts.", sent, len(alerts))
    return sent


if __name__ == "__main__":
    send_pending()