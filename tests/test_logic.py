"""Unit tests for the pure logic: no database, Slack or mail server needed."""
import numpy as np
import pandas as pd
import pytest

from control_tower.alerts.notify import build_message
from control_tower.alerts.notify_email import build_email
from control_tower.alerts.run_alerts import breaches
from control_tower.forecast.score_forecast import metrics
from control_tower.forecast.stock_vs_forecast import HORIZON_DAYS, first_stockout, risk_level

ALERTS = [
    {"severity": "critical", "message": "Budget Bulk Ltd averaged 3.0 days late"},
    {"severity": "warning", "message": "Stock-out rate was 7.4%"},
]


@pytest.mark.parametrize(
    "value, comparison, threshold, expected",
    [
        (5.1, "gt", 5.0, True),
        (5.0, "gt", 5.0, False),
        (4.9, "gt", 5.0, False),
        (4.9, "lt", 5.0, True),
        (5.0, "lt", 5.0, False),
        (5.1, "lt", 5.0, False),
    ],
)
def test_breaches_uses_strict_comparison(value, comparison, threshold, expected):
    assert breaches(value, comparison, threshold) is expected


def test_slack_message_lists_every_alert():
    text = build_message(ALERTS)
    assert "2 new alert(s)" in text
    assert "[CRITICAL] Budget Bulk Ltd averaged 3.0 days late" in text
    assert "[WARNING] Stock-out rate was 7.4%" in text


def test_email_subject_counts_alerts_and_critical():
    msg = build_email(ALERTS, "alerts@example.test", "ops@example.test")
    assert msg["Subject"] == "[Control Tower] 2 new alert(s), 1 critical"
    assert msg["To"] == "ops@example.test"
    assert "Budget Bulk Ltd" in msg.get_content()


def zeros() -> np.ndarray:
    """No deliveries or no demand over the 14-day horizon."""
    return np.zeros(HORIZON_DAYS)


def test_first_stockout_without_deliveries():
    demand = np.full(HORIZON_DAYS, 4.0)
    assert first_stockout(10, zeros(), demand) == 3  # stock goes 6, 2, -2


def test_first_stockout_delivery_pushes_it_later():
    demand = np.full(HORIZON_DAYS, 4.0)
    arrivals = zeros()
    arrivals[2] = 20  # 20 units arrive on day 3
    assert first_stockout(10, arrivals, demand) == 8


def test_first_stockout_none_when_stock_is_enough():
    assert first_stockout(1000, zeros(), np.full(HORIZON_DAYS, 4.0)) is None


def test_first_stockout_zero_stock_counts_as_day_one():
    assert first_stockout(0, zeros(), zeros()) == 1


@pytest.mark.parametrize(
    "expected, high, level",
    [
        (3, None, "high"),
        (7, None, "high"),
        (8, None, "medium"),
        (None, 5, "medium"),
        (None, None, "low"),
    ],
)
def test_risk_level(expected, high, level):
    assert risk_level(expected, high) == level


def test_metrics_known_values():
    result = metrics(pd.Series([10.0, 20.0]), pd.Series([12.0, 18.0]))
    assert result["rmse"] == pytest.approx(2.0)
    assert result["mae"] == pytest.approx(2.0)
    assert result["mape_pct"] == pytest.approx(15.0)
    assert result["wape_pct"] == pytest.approx(100 * 4 / 30)


def test_metrics_ignore_zero_sales_days_for_mape():
    result = metrics(pd.Series([0.0, 10.0]), pd.Series([1.0, 10.0]))
    assert result["mape_pct"] == pytest.approx(0.0)
    assert result["wape_pct"] == pytest.approx(10.0)