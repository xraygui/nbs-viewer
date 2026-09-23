import time as ttime
import logging
from typing import Iterable

# Backwards-compatible debug switches (legacy UI flags; prefer logger topics).
DEBUG_VARIABLES = {
    "PRINT_DEBUG": True,
}

# Canonical CLI / print_debug topics and their logger namespaces.
# Legacy DEBUG_* names remain as aliases.
CATEGORY_MAP = {
    None: "nbs_viewer",
    "": "nbs_viewer",
    "plots": "nbs_viewer.plots",
    "cache": "nbs_viewer.cache",
    "catalog": "nbs_viewer.catalog",
    "runlist": "nbs_viewer.runlist",
    "run": "nbs_viewer.run",
    "dimension": "nbs_viewer.dimensions",
    "display": "nbs_viewer.display",
    "pool": "nbs_viewer.pool",
    "perf": "perf",
    "DEBUG_PLOTS": "nbs_viewer.plots",
    "DEBUG_CATALOG": "nbs_viewer.catalog",
    "DEBUG_RUNLIST": "nbs_viewer.runlist",
    "DEBUG_RUN": "nbs_viewer.run",
    "DEBUG_DISPLAYMANAGER": "nbs_viewer.display",
}

KNOWN_TOPICS = (
    "plots",
    "cache",
    "catalog",
    "runlist",
    "run",
    "dimension",
    "display",
    "pool",
    "perf",
)

_top_level_model = None


def set_top_level_model(model) -> None:
    """
    Set the global top-level AppModel instance.

    Parameters
    ----------
    model : AppModel
        The AppModel instance to set as the global top-level model
    """
    global _top_level_model
    _top_level_model = model


def get_top_level_model():
    """
    Get the global top-level AppModel instance.

    Returns
    -------
    AppModel
        The global top-level AppModel instance

    Raises
    ------
    RuntimeError
        If called before the top-level model has been set
    """
    if _top_level_model is None:
        raise RuntimeError(
            "get_top_level_model() called before top-level model was set. "
            "This should never occur in normal operation."
        )
    return _top_level_model


def _resolve_logger_name(category: str | None) -> str:
    return CATEGORY_MAP.get(category, f"nbs_viewer.{category}")


def parse_debug_topics(values: Iterable[str] | None) -> list[str]:
    """
    Expand CLI topic arguments into a flat list.

    Parameters
    ----------
    values : iterable of str or None
        Topic arguments; each entry may be comma-separated.

    Returns
    -------
    list of str
        Deduplicated topic names in order of first appearance.
    """
    topics: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        for part in str(value).split(","):
            topic = part.strip().lower()
            if not topic or topic in seen:
                continue
            seen.add(topic)
            topics.append(topic)
    return topics


def enable_debug_topics(
    topics: Iterable[str],
    level: int = logging.DEBUG,
) -> list[str]:
    """
    Raise selected topic loggers to the given level.

    Parameters
    ----------
    topics : iterable of str
        Topic names or legacy category aliases (e.g. ``plots``, ``DEBUG_PLOTS``).
    level : int, optional
        Logging level to apply. Defaults to ``logging.DEBUG``.

    Returns
    -------
    list of str
        Resolved logger names that were enabled.
    """
    resolved: list[str] = []
    for topic in topics:
        name = topic.strip()
        if not name:
            continue
        # Accept canonical short names case-insensitively; preserve legacy keys.
        mapped = CATEGORY_MAP.get(name) or CATEGORY_MAP.get(name.lower())
        logger_name = mapped if mapped is not None else _resolve_logger_name(name)
        logging.getLogger(logger_name).setLevel(level)
        resolved.append(logger_name)
    return resolved


def turn_on_debugging():
    logging.getLogger().setLevel(logging.DEBUG)


def turn_off_debugging():
    logging.getLogger().setLevel(logging.INFO)


def print_debug(function_name, message, category=None, level: str = "DEBUG"):
    """Emit a structured log entry for debug-style messages.

    Parameters
    ----------
    function_name : str
        Function or scope name for context.
    message : str
        Message text.
    category : Optional[str]
        Topic or legacy category (e.g. ``plots``, ``DEBUG_CATALOG``).
        Mapped into a structured logger name like ``nbs_viewer.plots``.
    level : str, default "DEBUG"
        Logging level name to use (DEBUG, INFO, WARNING, ERROR).
    """
    logger_name = _resolve_logger_name(category)
    logger = logging.getLogger(logger_name)
    lvl = getattr(logging, (level or "DEBUG").upper(), logging.DEBUG)
    logger.log(lvl, f"[{function_name}] {message}")


def time_function(function_name=None, category=None):
    # If called with string argument, return decorator function
    if isinstance(function_name, str):

        def named_decorator(function):
            def wrapper(*args, **kwargs):
                start_time = ttime.time()
                result = function(*args, **kwargs)
                end_time = ttime.time()
                if category is None:
                    logger_name = "perf"
                else:
                    logger_name = _resolve_logger_name(category)
                logger = logging.getLogger(logger_name)
                logger.debug(f"{function_name} | {end_time - start_time:.6f}s")
                return result

            return wrapper

        return named_decorator

    # If called without arguments, function_name is actually the function
    elif callable(function_name):
        function = function_name
        name = function.__name__

        def wrapper(*args, **kwargs):
            start_time = ttime.time()
            result = function(*args, **kwargs)
            end_time = ttime.time()
            logger = logging.getLogger("perf")
            logger.debug(f"{name} | {end_time - start_time:.6f}s")
            return result

        return wrapper

    # Return decorator function for @time_function() case
    else:

        def decorator(function):
            name = function.__name__

            def wrapper(*args, **kwargs):
                start_time = ttime.time()
                result = function(*args, **kwargs)
                end_time = ttime.time()
                logger = logging.getLogger("perf")
                logger.debug(f"{name} | {end_time - start_time:.6f}s")
                return result

            return wrapper

        return decorator
