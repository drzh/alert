"""Provider registry."""

from __future__ import annotations

from alert.providers import BUILTIN_PROVIDERS
from alert.providers.base import AlertProvider

_PROVIDERS: dict[str, AlertProvider] = {provider.name: provider for provider in BUILTIN_PROVIDERS}


def get_provider(name: str) -> AlertProvider:
    try:
        return _PROVIDERS[name]
    except KeyError as exc:
        available = ", ".join(sorted(_PROVIDERS))
        raise KeyError(f"Unknown provider '{name}'. Available providers: {available}") from exc


def list_providers() -> tuple[str, ...]:
    return tuple(sorted(_PROVIDERS))
