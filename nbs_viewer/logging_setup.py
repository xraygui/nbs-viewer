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
    debug_topics: Optional[Iterable[str]] = None,
) -> None:
    """Configure application logging.

    Parameters
    ----------
    level : str
        Logging level name (e.g. DEBUG, INFO, WARNING, ERROR).
    log_file : Optional[str]
        If provided, also write logs to this file.
    http_to_file : Optional[str]
        If provided, write HTTP/network debug logs to this file.
    debug_topics : Optional[iterable of str]
        Topic names to enable at DEBUG without turning on full-app debug.
        When set and ``level`` is above DEBUG, the console handler accepts
        DEBUG so selected topic loggers can emit while others stay quiet.
    """
    from nbs_viewer.utils import enable_debug_topics, parse_debug_topics

    logging.captureWarnings(True)

    topics = parse_debug_topics(debug_topics)
    root_level = _parse_level(level)
    console_level = root_level
    if topics and console_level > logging.DEBUG:
        console_level = logging.DEBUG

    root = logging.getLogger()
    root.setLevel(root_level)

    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setLevel(console_level)
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

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(min(root_level, console_level))
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    if http_to_file:
        http_handler = logging.FileHandler(http_to_file, encoding="utf-8")
        http_handler.setLevel(logging.DEBUG)
        http_handler.setFormatter(formatter)
        http_handler.addFilter(
            _IncludeLoggers(("httpx", "httpcore", "tiled", "urllib3"))
        )
        root.addHandler(http_handler)

    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)
    logging.getLogger("tiled").setLevel(logging.INFO)
    logging.getLogger("bluesky_widgets.qt.kafka_dispatcher").setLevel(logging.INFO)

    if topics and root_level > logging.DEBUG:
        enable_debug_topics(topics)
