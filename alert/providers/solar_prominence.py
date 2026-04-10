"""Solar prominence record comparison provider."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Sequence

from alert.models import AlertItem, Attachment, StoredAlert, TargetConfig
from alert.providers._helpers import option_float, option_int, option_str, parse_tab_mapping, read_tab_file, write_tab_file
from alert.providers.base import AlertProvider


class SolarProminenceProvider(AlertProvider):
    name = "solar_prominence"
    default_email_title = "Solar Prominence Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        values = parse_tab_mapping(content)
        current_time = values.get("current_time")
        if not current_time:
            return []

        attachments: tuple[Attachment, ...] = ()
        attachment_path = option_str(target, "attachment_path")
        if attachment_path and Path(attachment_path).is_file():
            attachments = (Attachment(path=attachment_path),)

        return [
            AlertItem(
                item_id=current_time,
                message=(
                    f"Solar prominence at {current_time}<br/>"
                    f"Max distance: {values.get('prominence_max_distance_pixels', '0')} pixels<br/>"
                    f"Area: {values.get('prominence_area_pixels', '0')} pixels"
                ),
                occurred_at=current_time,
                metadata=values,
                attachments=attachments,
            )
        ]

    def should_alert(
        self,
        history: Sequence[StoredAlert],
        item: AlertItem,
        target: TargetConfig,
    ) -> bool:
        previous = _load_previous_record(target, history)
        current_time = _parse_datetime(item.occurred_at)
        if current_time is None:
            return False

        previous_time = _parse_datetime(previous.get("current_time"))
        trigger_minutes = option_int(target, "time_threshold_minutes", 10)
        if previous_time is not None and (current_time - previous_time).total_seconds() <= trigger_minutes * 60:
            return False

        current_distance = _metadata_float(item.metadata, "prominence_max_distance_pixels")
        current_area = _metadata_float(item.metadata, "prominence_area_pixels")
        previous_distance = _mapping_float(previous, "prominence_max_distance_pixels")
        previous_area = _mapping_float(previous, "prominence_area_pixels")
        distance_threshold = option_float(target, "distance_threshold", 20.0)
        area_threshold = option_float(target, "area_threshold", 2000.0)

        return (
            (current_distance > distance_threshold and current_distance > previous_distance)
            or (current_area > area_threshold and current_area > previous_area)
        )

    def after_target(
        self,
        target: TargetConfig,
        items: Sequence[AlertItem],
        pending: Sequence[AlertItem],
        content: str,
        *,
        persist: bool,
        notification_sent: bool,
    ) -> None:
        state_file = option_str(target, "state_file")
        if not persist or not state_file or not items:
            return

        values = parse_tab_mapping(content)
        current_time = _parse_datetime(values.get("current_time"))
        previous = read_tab_file(state_file)
        previous_time = _parse_datetime(previous.get("current_time"))

        if pending and notification_sent:
            write_tab_file(state_file, values)
            return

        if current_time is None or previous_time is None:
            return

        remove_minutes = option_int(target, "remove_threshold_minutes", 60)
        if (current_time - previous_time).total_seconds() > remove_minutes * 60:
            state_path = Path(state_file)
            if state_path.exists():
                state_path.unlink()


def _load_previous_record(target: TargetConfig, history: Sequence[StoredAlert]) -> dict[str, str]:
    state_file = option_str(target, "state_file")
    previous = read_tab_file(state_file)
    if previous:
        return previous

    if history:
        latest = history[0]
        return {
            key: str(value)
            for key, value in latest.metadata.items()
        }
    return {}


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _metadata_float(metadata: object, key: str) -> float:
    if isinstance(metadata, dict):
        return _mapping_float(metadata, key)
    return 0.0


def _mapping_float(mapping: object, key: str) -> float:
    if isinstance(mapping, dict):
        try:
            return float(mapping.get(key, 0))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


PROVIDER = SolarProminenceProvider()
