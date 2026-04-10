"""Command-line interface for alerts."""

from __future__ import annotations

import argparse
import logging
import sys

from alert.app import AlertRunner
from alert.config import load_config
from alert.infra.http import HttpClient
from alert.infra.notifier import ConsoleNotifier, SmtpNotifier
from alert.registry import list_providers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run configured alerts.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Logging level.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one or more alert sources.")
    run_parser.add_argument("--config", required=True, help="Path to the alert TOML configuration file.")
    run_scope = run_parser.add_mutually_exclusive_group(required=True)
    run_scope.add_argument("--source", help="Run a single configured source by name.")
    run_scope.add_argument("--all", action="store_true", help="Run all configured sources.")
    run_parser.add_argument("--dry-run", action="store_true", help="Do not persist or send real email.")

    subparsers.add_parser("list-providers", help="List built-in providers.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")

    if args.command == "list-providers":
        for provider_name in list_providers():
            print(provider_name)
        return 0

    config = load_config(args.config)
    notifier = ConsoleNotifier() if args.dry_run else _build_notifier(config)
    runner = AlertRunner(http_client=HttpClient(), notifier=notifier)

    if args.all:
        sources = config.sources
    else:
        sources = (config.get_source(args.source),)

    overall_status = 0
    for source in sources:
        summary = runner.run_source(source, persist=not args.dry_run)
        print(_format_summary(summary))
        if summary.errors:
            overall_status = 1

    return overall_status


def _build_notifier(config):
    if config.smtp is None:
        raise ValueError("SMTP configuration is required unless --dry-run is used.")
    return SmtpNotifier(config.smtp)


def _format_summary(summary) -> str:
    errors = f" errors={len(summary.errors)}" if summary.errors else ""
    return (
        f"source={summary.source_name}"
        f" checked={summary.targets_checked}"
        f" items={summary.items_seen}"
        f" alerts={summary.alerts_triggered}"
        f" saved={summary.alerts_saved}"
        f" notified={summary.notification_sent}"
        f" dry_run={summary.dry_run}"
        f"{errors}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
