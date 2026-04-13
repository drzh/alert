from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import alert.app as app_module
from alert.app import AlertRunner
from alert.models import AlertItem, Attachment, SourceConfig, TargetConfig
from alert.infra.http import HttpClient


@dataclass
class FakeHttpClient(HttpClient):
    payloads: dict[str, str] = field(default_factory=dict)

    def fetch_text(self, url: str, timeout_seconds: float | None = None) -> str:
        return self.payloads[url]


@dataclass
class RecordingNotifier:
    messages: list[tuple[str, str, tuple[Attachment, ...]]] = field(default_factory=list)

    def send(self, subject: str, body_html: str, attachments: tuple[Attachment, ...] = ()) -> None:
        self.messages.append((subject, body_html, attachments))


def test_runner_sends_and_persists_then_deduplicates(tmp_path: Path) -> None:
    source = SourceConfig(
        name="spaceweather_com",
        provider="spaceweather_com",
        db_file=str(tmp_path / "spaceweather_com.db"),
        targets=(TargetConfig(url="https://example.com/sw"),),
    )
    http = FakeHttpClient(payloads={"https://example.com/sw": '<p class="foo"><strong>Storm</strong></p>'})
    notifier = RecordingNotifier()
    runner = AlertRunner(http_client=http, notifier=notifier)

    first_summary = runner.run_source(source, persist=True)
    second_summary = runner.run_source(source, persist=True)

    assert first_summary.alerts_triggered == 1
    assert first_summary.alerts_saved == 1
    assert first_summary.notification_sent is True
    assert second_summary.alerts_triggered == 0
    assert second_summary.alerts_saved == 0
    assert second_summary.notification_sent is False
    assert len(notifier.messages) == 1


def test_runner_dry_run_notifies_without_persisting(tmp_path: Path) -> None:
    source = SourceConfig(
        name="spaceweather_com",
        provider="spaceweather_com",
        db_file=str(tmp_path / "spaceweather_com.db"),
        targets=(TargetConfig(url="https://example.com/sw"),),
    )
    http = FakeHttpClient(payloads={"https://example.com/sw": '<p class="foo"><strong>Storm</strong></p>'})
    notifier = RecordingNotifier()
    runner = AlertRunner(http_client=http, notifier=notifier)

    dry_run_summary = runner.run_source(source, persist=False)
    second_dry_run_summary = runner.run_source(source, persist=False)

    assert dry_run_summary.alerts_triggered == 1
    assert dry_run_summary.alerts_saved == 0
    assert dry_run_summary.dry_run is True
    assert second_dry_run_summary.alerts_triggered == 1
    assert len(notifier.messages) == 2


def test_runner_passes_attachments_from_alert_items(tmp_path: Path) -> None:
    attachment = tmp_path / "prominence.png"
    attachment.write_bytes(b"png")
    content = "\n".join(
        [
            "current_time\t2026-04-07T20:00:00",
            "prominence_max_distance_pixels\t150",
            "prominence_area_pixels\t2200",
        ]
    )
    source = SourceConfig(
        name="solar_prominence",
        provider="solar_prominence",
        db_file=str(tmp_path / "solar_prominence.db"),
        targets=(
            TargetConfig(
                url="file:///tmp/prominence.txt",
                options={"attachment_path": str(attachment), "area_threshold": 1000},
            ),
        ),
    )
    http = FakeHttpClient(payloads={"file:///tmp/prominence.txt": content})
    notifier = RecordingNotifier()
    runner = AlertRunner(http_client=http, notifier=notifier)

    summary = runner.run_source(source, persist=False)

    assert summary.alerts_triggered == 1
    assert len(notifier.messages) == 1
    assert notifier.messages[0][2][0].path == str(attachment)


def test_runner_uses_provider_custom_fetch_content(tmp_path: Path, monkeypatch) -> None:
    @dataclass
    class CustomProvider:
        name: str = "custom"
        default_email_title: str = "Custom"

        def fetch_content(self, target: TargetConfig, http_client: HttpClient) -> str:
            return "custom-payload"

        def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
            assert content == "custom-payload"
            return [AlertItem(item_id="custom-item", message="Custom alert")]

        def should_alert(self, history: list[object], item: AlertItem, target: TargetConfig) -> bool:
            return True

        def build_subject(self, source: SourceConfig, alerts_by_target: dict[str, list[AlertItem]]) -> str:
            return "Custom Subject"

        def after_target(
            self,
            target: TargetConfig,
            items: list[AlertItem],
            pending: list[AlertItem],
            content: str,
            *,
            persist: bool,
            notification_sent: bool,
        ) -> None:
            return None

    source = SourceConfig(
        name="custom",
        provider="custom",
        db_file=str(tmp_path / "custom.db"),
        targets=(TargetConfig(url="custom://target"),),
    )
    notifier = RecordingNotifier()
    runner = AlertRunner(http_client=FakeHttpClient(), notifier=notifier)

    monkeypatch.setattr(app_module, "get_provider", lambda name: CustomProvider())

    summary = runner.run_source(source, persist=False)

    assert summary.alerts_triggered == 1
    assert notifier.messages[0][0] == "Custom Subject"
