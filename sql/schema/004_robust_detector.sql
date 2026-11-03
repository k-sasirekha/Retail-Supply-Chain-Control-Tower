-- Allow a third detector name in detected_anomalies
ALTER TABLE detected_anomalies DROP CONSTRAINT IF EXISTS detected_anomalies_detector_check;
ALTER TABLE detected_anomalies ADD CONSTRAINT detected_anomalies_detector_check
    CHECK (detector IN ('zscore', 'isolation_forest', 'robust_zscore'));