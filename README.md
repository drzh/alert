# Alert

A modular alert runner for the jobs that previously lived as one-off scripts under `alert`.

The repo is organized so future maintenance stays predictable:

- typed config and models
- built-in provider registry
- shared HTTP, notification, and SQLite layers
- provider-specific parsing and alert rules
- one CLI for running one source or all sources

## Highlights

- Multiple targets per source, each with its own URL and threshold
- Provider-specific options for blacklists, state files, output files, and attachments
- SQLite-backed alert history with dry-run support
- SMTP secrets loaded from environment variables instead of hardcoded credentials
- Local file targets supported by config; relative file paths are converted to `file://` URIs automatically
- Tests for config, providers, runner behavior, and CLI wiring

## Project Layout

```text
alert/
  __main__.py
  app.py
  cli.py
  config.py
  models.py
  registry.py
  infra/
    http.py
    notifier.py
    repository.py
  providers/
    ariss.py
    aurora.py
    aurora_gfz.py
    bz.py
    cc.py
    cl.py
    ha_comet.py
    rocketlaunch.py
    sd.py
    solar_prominence.py
    solarspot.py
    spaceweather_com.py
    spaceweather_gov.py
    spaceweather_gov_alerts.py
alerts.example.toml
tests/
```

## Requirements

- Python 3.11+ recommended
- `pytest` to run the test suite

The application itself uses only the Python standard library at runtime.

## Commands

List built-in providers:

```bash
python3 -m alert.cli list-providers
```

Run one configured source:

```bash
python3 -m alert.cli run --config alerts.example.toml --source aurora --dry-run
```

Run all configured sources:

```bash
python3 -m alert.cli run --config alerts.example.toml --all --dry-run
```

Run with real SMTP delivery:

```bash
export ALERT_SMTP_PASSWORD="your-app-password"
python3 -m alert.cli run --config alerts.example.toml --source spaceweather_com
```

## Config Model

The config file is TOML.

- `source`
  One logical alert source with one provider, one database file, one email title, and one or more targets.
- `target`
  One URL or local file plus target-specific options such as `threshold`, `blacklist_file`, or `state_file`.

Relative `db_file`, `*_file`, `*_path`, and `*_dir` values are resolved relative to the TOML file.

## Provider Options

- `sd` and `cc`
  Use `blacklist_file = "..."` or `blacklist = ["regex1", "regex2"]`.
- `aurora`
  Supports `state_file` and `table_output_file` to match the legacy SWPC 3-day forecast job.
- `solarspot`
  Supports `state_file` for the old `solarspot.val` workflow.
- `solar_prominence`
  Supports a local file target plus `state_file`, `attachment_path`, `time_threshold_minutes`, `remove_threshold_minutes`, `distance_threshold`, and `area_threshold`.
- `keep_records`
  Can be raised per source if you want legacy retention like `1000000`.

## Active Cron Migration

These active cron-backed jobs are now covered by built-in providers:

- `report_sd.pl` -> `sd`
- `report.py -w spaceweather_com` -> `spaceweather_com`
- `report.py -w bz` -> `bz`
- `report.py -w spaceweather_gov` -> `spaceweather_gov`
- `report.py -w spaceweather_gov_alerts` -> `spaceweather_gov_alerts`
- `report_aurora.pl` -> `aurora`
- `report.py -w aurora_gfz` -> `aurora_gfz`
- `report_cl.py` -> `cl`
- `report_cc.pl` -> `cc`
- `report_solarspot.py` -> `solarspot`
- `report_ariss.pl` -> `ariss`
- `report_ha_comet.pl` -> `ha_comet`
- `report_rocketlaunch.py` -> `rocketlaunch`
- `report_solar_prominence.py` -> `solar_prominence`

Typical migrated commands now look like:

```bash
python3 -m alert.cli run --config alerts.toml --source sd
python3 -m alert.cli run --config alerts.toml --source aurora
python3 -m alert.cli run --config alerts.toml --source solar_prominence
```

## Example Config

`alerts.example.toml` includes examples for the active cron-backed sources, including:

- multi-target web sources like `sd`, `cl`, and `ha_comet`
- state-file jobs like `aurora` and `solarspot`
- a local-file-and-attachment job for `solar_prominence`

## Dry Run Behavior

`--dry-run`:

- fetches or reads target content
- applies alert rules
- prints the email subject and body to stdout
- prints attachment names when present
- prints a run summary
- does not write SQLite history
- does not update provider state files
- does not send real email

## Tests

Run the full suite:

```bash
pytest -q /home/celaeno/script/alert/tests
```

## Current Built-In Providers

- `ariss`
- `aurora`
- `aurora_gfz`
- `bz`
- `cc`
- `cl`
- `ha_comet`
- `rocketlaunch`
- `sd`
- `solar_prominence`
- `solarspot`
- `spaceweather_com`
- `spaceweather_gov`
- `spaceweather_gov_alerts`
