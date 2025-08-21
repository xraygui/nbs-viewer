import logging
from typing import Optional, Iterable


def _parse_level(level: str) -> int:
    level = (level or "INFO").upper()
    return getattr(logging, level, logging.INFO)


class _ExcludeLoggers(logging.Filter):
    def __init__(self, excluded_prefixes: Iterable[str]):
        super().__init__()
        self._excluded = tuple(excluded_prefixes)

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        name = record.name or ""
        return not name.startswith(self._excluded)


class _IncludeLoggers(logging.Filter):
    def __init__(self, included_prefixes: Iterable[str]):
        super().__init__()
        self._included = tuple(included_prefixes)

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        name = record.name or ""
        return name.startswith(self._included)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    http_to_file: Optional[str] = None,
) -> None:
    """Configure application logging.

    Parameters
    ----------
    level : str
        Logging level name (e.g., DEBUG, INFO, WARNING, ERROR).
    log_file : Optional[str]
        If provided, also write logs to this file.
    """
    logging.captureWarnings(True)

    # Root logger
    root = logging.getLogger()
    root.setLevel(_parse_level(level))

    # Clear existing handlers (idempotent setup)
    for h in list(root.handlers):
        root.removeHandler(h)

    # Console handler (exclude noisy network loggers)
    console = logging.StreamHandler()
    console.setLevel(_parse_level(level))
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console.setFormatter(formatter)
    console.addFilter(
        _ExcludeLoggers(
            (
                "httpx",
                "httpcore",
                "tiled",
                "urllib3",
            )
        )
    )
    root.addHandler(console)

    # Optional file handler (all logs)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(_parse_level(level))
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Optional separate HTTP/file-network logs at full verbosity
    if http_to_file:
        http_handler = logging.FileHandler(http_to_file, encoding="utf-8")
        http_handler.setLevel(logging.DEBUG)
        http_handler.setFormatter(formatter)
        http_handler.addFilter(
            _IncludeLoggers(("httpx", "httpcore", "tiled", "urllib3"))
        )
        root.addHandler(http_handler)

    # Set a sensible default level for third-party noisy loggers if needed
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)
    logging.getLogger("tiled").setLevel(logging.INFO)
