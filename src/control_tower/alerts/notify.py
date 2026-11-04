"""Send pending alerts from alert_log to Slack, one message per run.

Reads SLACK_WEBHOOK_URL from the environment (.env). If it is not set, nothing is sent and
the alerts stay 'pending', so they go out once a webhook is configured.
"""
import json
import logging
import os
import urllib.error
import urllib.request

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10
MAX_ALERTS_PER_MESSAGE = 20


def load_pending(conn: Connection) -> list[dict]:
    """Alerts not yet sent to Slack, critical ones first."""
    rows = conn.execute(
        text(
            "SELECT alert_id, rule_name, severity, message, data_ts FROM alert_log "
            "WHERE slack_status = 'pending' ORDER BY (severity = 'critical') DESC, alert_id"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def build_message(alerts: list[dict]) -> str:
    """Plain-text Slack message listing the alerts."""
    lines = [f"*Control Tower: {len(alerts)} new alert(s)*"]
    for a in alerts:
        lines.append(f"[{a['severity'].upper()}] {a['message']}")
    return "\n".join(lines)


def post_slack(url: str, message: str) -> bool:
    """POST a message to a Slack incoming webhook. Returns True on success."""
    data = json.dumps({"text": message}).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError) as exc:
        log.error("Slack post failed: %s", exc)  # the URL is a secret, so it is never logged
        return False


def mark(conn: Connection, alert_ids: list[int], status: str) -> None:
    """Set slack_status for the given alerts."""
    conn.execute(
        text("UPDATE alert_log SET slack_status = :s WHERE alert_id = ANY(:ids)"),
        {"s": status, "ids": alert_ids},
    )


def send_pending() -> int:
    """Send every pending alert to Slack. Returns how many were sent."""
    url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    engine = create_engine(config.database_url())
    sent = 0
    with engine.begin() as conn:
        alerts = load_pending(conn)
        if not alerts:
            log.info("No pending alerts.")
            return 0
        if not url:
            log.warning("SLACK_WEBHOOK_URL is not set. %d alerts stay pending.", len(alerts))
            return 0
        for i in range(0, len(alerts), MAX_ALERTS_PER_MESSAGE):
            chunk = alerts[i : i + MAX_ALERTS_PER_MESSAGE]
            ok = post_slack(url, build_message(chunk))
            mark(conn, [a["alert_id"] for a in chunk], "sent" if ok else "failed")
            sent += len(chunk) if ok else 0
    log.info("Sent %d of %d pending alerts to Slack.", sent, len(alerts))
    return sent


if __name__ == "__main__":
    send_pending()
    