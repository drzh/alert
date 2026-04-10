"""Solar spot area alert provider."""

from __future__ import annotations

from typing import Sequence

from alert.models import AlertItem, StoredAlert, TargetConfig
from alert.providers._helpers import option_str, read_tab_file, write_tab_file
from alert.providers.base import AlertProvider


class SolarSpotProvider(AlertProvider):
    name = "solarspot"
    default_email_title = "Solar Spot Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        max_area = _extract_max_area(content)
        if max_area is None:
            return []
        return [
            AlertItem(
                item_id=f"max:{max_area}",
                message=f"Maximum Solar Spot: {max_area}",
                value=str(max_area),
                metadata={"stable_id": "max"},
            )
        ]

    def should_alert(
        self,
        history: Sequence[StoredAlert],
        item: AlertItem,
        target: TargetConfig,
    ) -> bool:
        threshold = target.threshold if target.threshold is not None else 700.0
        current = _to_int(item.value)
        if current is None or current <= threshold:
            return False

        state_file = option_str(target, "state_file")
        previous_state = read_tab_file(state_file)
        if "max" in previous_state:
            previous = _to_int(previous_state["max"])
            return previous is None or current != previous

        if history:
            previous = _to_int(history[0].value)
            return previous is None or current != previous
        return True

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
        if not persist or not notification_sent or not pending or not state_file:
            return
        write_tab_file(state_file, {"max": pending[0].value or "0"}, order=("max",))


def _extract_max_area(content: str) -> int | None:
    flag = False
    max_area = 0
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not flag:
            if line.startswith("Nmbr Location"):
                flag = True
            continue
        if not line[0].isdigit():
            break
        columns = line.split()
        if len(columns) < 4:
            continue
        try:
            max_area = max(max_area, int(columns[3]))
        except ValueError:
            continue
    return max_area if flag else None


def _to_int(value: object) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


PROVIDER = SolarSpotProvider()
