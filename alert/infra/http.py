"""HTTP client wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from urllib.error import URLError
from urllib.request import Request, urlopen


class FetchError(RuntimeError):
    """Raised when content cannot be fetched from a URL."""


@dataclass
class HttpClient:
    """Simple HTTP client with retry support."""

    timeout_seconds: float = 30.0
    retries: int = 2
    user_agent: str = "alert-bot/1.0"

    def fetch_text(self, url: str, timeout_seconds: float | None = None) -> str:
        timeout = timeout_seconds or self.timeout_seconds
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                request = Request(url, headers={"User-Agent": self.user_agent})
                with urlopen(request, timeout=timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.read().decode(charset, errors="replace")
            except (URLError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    sleep(0.25 * attempt)

        raise FetchError(f"Failed to fetch {url}: {last_error}")
