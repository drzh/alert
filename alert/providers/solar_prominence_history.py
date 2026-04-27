"""Maintain a rolling solar prominence intensity history."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from alert.providers._helpers import parse_tab_mapping


FIELDNAMES = (
    "obs_time",
    "intensity_max",
    "intensity_max_longitude",
    "intensity_max_latitude",
)
LEGACY_FIELDNAMES = ("obs_time", "intensity_max")
CURRENT_REQUIRED_FIELDNAMES = (
    "obs_time",
    "intensity_max",
    "intensity_max_latitude",
)
LONGITUDE_FIELD_ALIASES = ("intensity_max_longitude", "intensity_max_longtitude")


@dataclass(frozen=True)
class HistoryRecord:
    obs_time: str
    intensity_max: str
    intensity_max_longitude: str
    intensity_max_latitude: str


def update_history(input_file: Path, history_file: Path, *, hours: float = 120) -> list[HistoryRecord]:
    if hours <= 0:
        raise ValueError("hours must be greater than zero")

    current = _read_current_record(input_file)
    records = _read_history(history_file)
    records[current.obs_time] = current

    latest_time = max(_parse_obs_time(record.obs_time) for record in records.values())
    cutoff_time = latest_time - timedelta(hours=hours)
    kept_records = [
        record
        for record in records.values()
        if _parse_obs_time(record.obs_time) >= cutoff_time
    ]
    kept_records.sort(key=lambda record: _parse_obs_time(record.obs_time))

    _write_history(history_file, kept_records)
    return kept_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update solar prominence intensity history.")
    parser.add_argument("--input", required=True, type=Path, help="Current solar prominence tab file.")
    parser.add_argument("--history", required=True, type=Path, help="Rolling history TSV file.")
    parser.add_argument("--hours", default=120.0, type=float, help="Hours to keep from the latest obs_time.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    update_history(args.input, args.history, hours=args.hours)
    return 0


def _read_current_record(input_file: Path) -> HistoryRecord:
    values = parse_tab_mapping(input_file.read_text(encoding="utf-8"))
    missing_fields = [
        field
        for field in CURRENT_REQUIRED_FIELDNAMES
        if not values.get(field)
    ]
    intensity_max_longitude = _get_longitude_value(values)
    if not intensity_max_longitude:
        missing_fields.append("intensity_max_longitude")
    if missing_fields:
        raise ValueError(
            f"{input_file} is missing required field(s): {', '.join(missing_fields)}"
        )

    obs_time = values["obs_time"]
    _parse_obs_time(obs_time)
    return HistoryRecord(
        obs_time=obs_time,
        intensity_max=_round_intensity_max(values["intensity_max"]),
        intensity_max_longitude=_round_coordinate(
            intensity_max_longitude,
            "intensity_max_longitude",
        ),
        intensity_max_latitude=_round_coordinate(
            values["intensity_max_latitude"],
            "intensity_max_latitude",
        ),
    )


def _read_history(history_file: Path) -> dict[str, HistoryRecord]:
    if not history_file.is_file():
        return {}

    records: dict[str, HistoryRecord] = {}
    with history_file.open(encoding="utf-8", newline="") as file_obj:
        reader = csv.DictReader(file_obj, delimiter="\t")
        if reader.fieldnames is None or any(field not in reader.fieldnames for field in LEGACY_FIELDNAMES):
            return {}

        for row in reader:
            obs_time = (row.get("obs_time") or "").strip()
            intensity_max = (row.get("intensity_max") or "").strip()
            intensity_max_longitude = _get_longitude_value(row)
            intensity_max_latitude = (row.get("intensity_max_latitude") or "").strip()
            if not obs_time or not intensity_max:
                continue
            try:
                _parse_obs_time(obs_time)
                rounded_intensity_max = _round_intensity_max(intensity_max)
                rounded_longitude = _round_optional_coordinate(
                    intensity_max_longitude,
                    "intensity_max_longitude",
                )
                rounded_latitude = _round_optional_coordinate(
                    intensity_max_latitude,
                    "intensity_max_latitude",
                )
            except ValueError:
                continue
            records[obs_time] = HistoryRecord(
                obs_time=obs_time,
                intensity_max=rounded_intensity_max,
                intensity_max_longitude=rounded_longitude,
                intensity_max_latitude=rounded_latitude,
            )

    return records


def _write_history(history_file: Path, records: Iterable[HistoryRecord]) -> None:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = history_file.with_name(f"{history_file.name}.tmp")
    with tmp_file.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=FIELDNAMES,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "obs_time": record.obs_time,
                    "intensity_max": record.intensity_max,
                    "intensity_max_longitude": record.intensity_max_longitude,
                    "intensity_max_latitude": record.intensity_max_latitude,
                }
            )
    tmp_file.replace(history_file)


def _round_intensity_max(value: str) -> str:
    return _round_decimal_to_int(value, "intensity_max")


def _round_coordinate(value: str, field_name: str) -> str:
    return _round_decimal_to_int(value, field_name)


def _round_optional_coordinate(value: str, field_name: str) -> str:
    if not value:
        return ""
    return _round_coordinate(value, field_name)


def _round_decimal_to_int(value: str, field_name: str) -> str:
    try:
        rounded_value = Decimal(value.strip()).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return str(int(rounded_value))
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc


def _get_longitude_value(values: dict[str, str]) -> str:
    for field_name in LONGITUDE_FIELD_ALIASES:
        value = (values.get(field_name) or "").strip()
        if value:
            return value
    return ""


def _parse_obs_time(value: str) -> datetime:
    obs_time = datetime.fromisoformat(value)
    if obs_time.tzinfo is not None:
        obs_time = obs_time.astimezone(timezone.utc).replace(tzinfo=None)
    return obs_time


if __name__ == "__main__":
    raise SystemExit(main())
