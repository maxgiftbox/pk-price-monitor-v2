from datetime import datetime, timezone

from src.data_sources.access_analytics import AccessAnalyticsWriter, AccessEvent


class Worksheet:
    def __init__(self):
        self.rows = []

    def append_row(self, row, value_input_option):
        self.rows.append((row, value_input_option))


def test_writer_appends_utc_local_time_path_and_ip(monkeypatch):
    monkeypatch.setenv("ACCESS_ANALYTICS_TIMEZONE", "Asia/Dhaka")
    writer = AccessAnalyticsWriter()
    worksheet = Worksheet()
    writer._worksheet = worksheet

    writer.record(AccessEvent(
        session_id="7c15ec3a-7ab9-4f15-8a6c-aaf430b9a5a9",
        event_type="session_start",
        path="/social-intelligence",
        ip_address="203.0.113.10",
        occurred_at=datetime(2026, 11, 26, 4, 30, tzinfo=timezone.utc),
    ))

    row, mode = worksheet.rows[0]
    assert mode == "RAW"
    assert row == [
        "2026-11-26T04:30:00+00:00",
        "2026-11-26T10:30:00+06:00",
        "session_start",
        "7c15ec3a-7ab9-4f15-8a6c-aaf430b9a5a9",
        "/social-intelligence",
        "203.0.113.10",
    ]
