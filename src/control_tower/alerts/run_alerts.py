"""Alert engine: check KPI thresholds from alert_config and deduplicate against alert_log.

Default is a dry run that only prints. With --record, new alerts are written to alert_log
(status 'recorded') so deduplication can be tested before any message is sent.
"""
import argparse
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MIN_SUPPLIER_DELIVERIES = 3


@dataclass
class Candidate:
    """One threshold breach that may become an alert."""

    rule_name: str
    entity_key: str
    severity: str
    message: str
    metric_value: float
    threshold: float
    data_ts: datetime


def breaches(value: float, comparison: str, threshold: float) -> bool:
    """True if the value is on the wrong side of the threshold ('gt' or 'lt')."""
    return value > threshold if comparison == "gt" else value < threshold


def load_rules(conn: Connection) -> dict[str, dict]:
    """Enabled rules from alert_config, keyed by rule name."""
    rows = conn.execute(
        text(
            "SELECT rule_name, comparison, threshold, min_volume, severity, cooldown_hours "
            "FROM alert_config WHERE enabled"
        )
    ).mappings().all()
    return {r["rule_name"]: dict(r) for r in rows}


def check_stockout_rate(conn: Connection, rule: dict, clock: datetime) -> list[Candidate]:
    """Latest day's stock-out rate (%) against the threshold."""
    row = conn.execute(
        text("SELECT day, stockout_rate_pct FROM v_kpi_stockout_daily ORDER BY day DESC LIMIT 1")
    ).first()
    if row is None:
        return []
    day, value, thr = row[0], float(row[1]), float(rule["threshold"])
    if not breaches(value, rule["comparison"], thr):
        return []
    msg = f"Stock-out rate was {value:.1f}% on {day} (threshold {thr:.1f}%)"
    return [Candidate(rule["rule_name"], "global", rule["severity"], msg, value, thr,
                      datetime.combine(day, datetime.min.time()))]


def check_ontime_rate(conn: Connection, rule: dict, clock: datetime) -> list[Candidate]:
    """On-time delivery (%) over the last 7 data days against the threshold."""
    row = conn.execute(
        text(
            "WITH last AS (SELECT max(day) AS d FROM v_kpi_ontime_daily) "
            "SELECT (SELECT d FROM last), 100.0 * sum(on_time) / NULLIF(sum(shipments), 0), sum(shipments) "
            "FROM v_kpi_ontime_daily WHERE day > (SELECT d FROM last) - 7"
        )
    ).first()
    if row is None or row[1] is None:
        return []
    day, value, thr = row[0], float(row[1]), float(rule["threshold"])
    if not breaches(value, rule["comparison"], thr):
        return []
    msg = f"On-time delivery was {value:.1f}% over the 7 days to {day} on {int(row[2])} shipments (threshold {thr:.1f}%)"
    return [Candidate(rule["rule_name"], "global", rule["severity"], msg, value, thr,
                      datetime.combine(day, datetime.min.time()))]


def check_supplier_lateness(conn: Connection, rule: dict, clock: datetime) -> list[Candidate]:
    """Average days late per supplier over the last 30 days before the clock."""
    rows = conn.execute(
        text(
            "SELECT s.supplier_id, s.supplier_name, "
            "avg(EXTRACT(epoch FROM (d.received_ts - d.expected_ts)) / 86400)::float8 AS avg_late, count(*) AS n "
            "FROM supplier_deliveries d JOIN suppliers s ON s.supplier_id = d.supplier_id "
            "WHERE d.received_ts IS NOT NULL AND d.received_ts < :clock "
            "AND d.received_ts >= :clock - interval '30 days' "
            "GROUP BY s.supplier_id, s.supplier_name HAVING count(*) >= :min_n"
        ),
        {"clock": clock, "min_n": MIN_SUPPLIER_DELIVERIES},
    ).all()
    thr = float(rule["threshold"])
    found = []
    for sid, name, avg_late, n in rows:
        if breaches(float(avg_late), rule["comparison"], thr):
            msg = f"{name} averaged {float(avg_late):.1f} days late over {n} deliveries in the last 30 days (threshold {thr:.1f})"
            found.append(Candidate(rule["rule_name"], f"supplier:{sid}", rule["severity"], msg,
                                   float(avg_late), thr, clock))
    return found


def check_days_of_inventory(conn: Connection, rule: dict, clock: datetime) -> list[Candidate]:
    """Products selling at least min_volume a day with fewer days of inventory than the threshold."""
    min_volume = float(rule["min_volume"] or 0)
    rows = conn.execute(
        text(
            "SELECT product_id, product_name, on_hand, daily_demand_14d, days_of_inventory, as_of_day "
            "FROM v_kpi_days_of_inventory "
            "WHERE days_of_inventory IS NOT NULL AND daily_demand_14d >= :min_volume"
        ),
        {"min_volume": min_volume},
    ).all()
    thr = float(rule["threshold"])
    found = []
    for pid, name, on_hand, demand, doi, as_of in rows:
        if breaches(float(doi), rule["comparison"], thr):
            msg = (f"{name}: {float(doi):.1f} days of inventory left ({on_hand} on hand, "
                   f"selling {float(demand):.1f}/day, threshold {thr:.1f})")
            found.append(Candidate(rule["rule_name"], f"product:{pid}", rule["severity"], msg,
                                   float(doi), thr, datetime.combine(as_of, datetime.min.time())))
    return found


CHECKS: dict[str, Callable[[Connection, dict, datetime], list[Candidate]]] = {
    "stockout_rate_high": check_stockout_rate,
    "ontime_rate_low": check_ontime_rate,
    "supplier_late_days_high": check_supplier_lateness,
    "days_of_inventory_low": check_days_of_inventory,
}


def is_suppressed(conn: Connection, rule_name: str, entity_key: str, cooldown_hours: int) -> bool:
    """True if the same rule already alerted for this entity inside its cooldown."""
    return bool(
        conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM alert_log WHERE rule_name = :r AND entity_key = :e "
                "AND fired_at > now() - make_interval(hours => :h))"
            ),
            {"r": rule_name, "e": entity_key, "h": int(cooldown_hours)},
        ).scalar_one()
    )


def record(conn: Connection, c: Candidate) -> None:
    """Write an alert to alert_log (status 'recorded': nothing has been sent)."""
    conn.execute(
        text(
            "INSERT INTO alert_log (rule_name, entity_key, severity, message, metric_value, threshold, "
            "data_ts, slack_status, email_status) VALUES (:rule_name, :entity_key, :severity, :message, "
            ":metric_value, :threshold, :data_ts, 'recorded', 'recorded')"
        ),
        asdict(c),
    )


def run(record_alerts: bool) -> list[Candidate]:
    """Check every enabled rule; return the alerts that are new (not suppressed)."""
    engine = create_engine(config.database_url())
    fired: list[Candidate] = []
    with engine.begin() as conn:
        clock = conn.execute(text("SELECT watermark_ts FROM replay_state WHERE id = 1")).scalar_one()
        rules = load_rules(conn)
        mode = "RECORD" if record_alerts else "DRY RUN"
        log.info("Replay clock %s | %d enabled rules | mode: %s", clock, len(rules), mode)
        for name, check in CHECKS.items():
            rule = rules.get(name)
            if rule is None:
                log.info("%-24s disabled or missing, skipped", name)
                continue
            candidates = check(conn, rule, clock)
            new = suppressed = 0
            for c in candidates:
                if is_suppressed(conn, name, c.entity_key, rule["cooldown_hours"]):
                    suppressed += 1
                    continue
                new += 1
                fired.append(c)
                print(f"  [{c.severity.upper()}] {c.message}")
                if record_alerts:
                    record(conn, c)
            log.info("%-24s breaches=%d new=%d suppressed=%d", name, len(candidates), new, suppressed)
    return fired


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description="Check alert rules against the KPI views.")
    parser.add_argument("--record", action="store_true", help="write new alerts to alert_log")
    args = parser.parse_args()
    fired = run(args.record)
    log.info("%s %d new alerts.", "Recorded" if args.record else "Would fire", len(fired))


if __name__ == "__main__":
    main()