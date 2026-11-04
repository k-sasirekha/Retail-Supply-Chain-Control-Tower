-- Starting thresholds. ON CONFLICT DO NOTHING means re-running this never overwrites
-- a threshold you have changed in the table.
INSERT INTO alert_config (rule_name, description, comparison, threshold, min_volume, severity, cooldown_hours) VALUES
 ('stockout_rate_high',     'Latest daily stock-out rate (%) is above the threshold',                          'gt', 20.0, NULL, 'warning',  6),
 ('ontime_rate_low',        'On-time delivery (%) over the last 7 days is below the threshold',                'lt', 40.0, NULL, 'warning',  6),
 ('supplier_late_days_high','A supplier averages more late days than the threshold over the last 30 days',    'gt',  2.5, NULL, 'critical', 6),
 ('days_of_inventory_low',  'A product has fewer days of inventory than the threshold (min daily demand set)', 'lt',  2.0, 5.0,  'critical', 6)
ON CONFLICT (rule_name) DO NOTHING;