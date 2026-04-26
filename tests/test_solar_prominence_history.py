from __future__ import annotations

from pathlib import Path

import pytest

from alert.providers.solar_prominence_history import update_history


def test_update_solar_prominence_history_upserts_current_record(tmp_path: Path) -> None:
    current_file = tmp_path / "AIAsynoptic0304.prominence.txt"
    history_file = tmp_path / "AIAsynoptic0304.hist.txt"
    current_file.write_text(
        "\n".join(
            [
                "current_time\t2026-04-25T07:31:08.410296+00:00",
                "obs_time\t2026-04-25T07:24:53.136",
                "intensity_max\t294.625",
                "intensity_max_pixel_x\t554",
                "intensity_max_pixel_y\t651",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    history_file.write_text(
        "\n".join(
            [
                "obs_time\tintensity_max\tintensity_max_pixel_x\tintensity_max_pixel_y",
                "2026-04-25T06:00:00.000\t100\t10\t20",
                "2026-04-25T07:24:53.136\t111\t30\t40",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = update_history(current_file, history_file, hours=120)

    assert [record.obs_time for record in records] == [
        "2026-04-25T06:00:00.000",
        "2026-04-25T07:24:53.136",
    ]
    assert history_file.read_text(encoding="utf-8") == (
        "obs_time\tintensity_max\tintensity_max_pixel_x\tintensity_max_pixel_y\n"
        "2026-04-25T06:00:00.000\t100\t10\t20\n"
        "2026-04-25T07:24:53.136\t295\t554\t651\n"
    )


def test_update_solar_prominence_history_prunes_from_latest_obs_time(tmp_path: Path) -> None:
    current_file = tmp_path / "AIAsynoptic0304.prominence.txt"
    history_file = tmp_path / "AIAsynoptic0304.hist.txt"
    current_file.write_text(
        "\n".join(
            [
                "obs_time\t2026-04-25T12:00:00",
                "intensity_max\t450.5",
                "intensity_max_pixel_x\t500",
                "intensity_max_pixel_y\t600",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    history_file.write_text(
        "\n".join(
            [
                "obs_time\tintensity_max",
                "2026-04-20T11:59:59\t10",
                "2026-04-20T12:00:00\t20",
                "2026-04-21T12:00:00\t30",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    update_history(current_file, history_file, hours=120)

    assert history_file.read_text(encoding="utf-8") == (
        "obs_time\tintensity_max\tintensity_max_pixel_x\tintensity_max_pixel_y\n"
        "2026-04-20T12:00:00\t20\t\t\n"
        "2026-04-21T12:00:00\t30\t\t\n"
        "2026-04-25T12:00:00\t451\t500\t600\n"
    )


def test_update_solar_prominence_history_requires_current_fields(tmp_path: Path) -> None:
    current_file = tmp_path / "AIAsynoptic0304.prominence.txt"
    current_file.write_text("obs_time\t2026-04-25T12:00:00\n", encoding="utf-8")

    with pytest.raises(ValueError, match="intensity_max"):
        update_history(current_file, tmp_path / "AIAsynoptic0304.hist.txt")
