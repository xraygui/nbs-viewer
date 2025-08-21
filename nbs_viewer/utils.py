import time as ttime
import logging

# Backwards-compatible debug switches (no-ops with logging but preserved for now)
# Legacy switches retained for CLI flags; prefer logger configuration.
DEBUG_VARIABLES = {
    "PRINT_DEBUG": True,
    "DEBUG_CATALOG": True,
    "DEBUG_PLOTS": False,
    "DEBUG_RUNLIST": False,
    "cache": True,
    "dimension": True,
}


# Map legacy/debug categories to structured logger namespaces
CATEGORY_MAP = {
    None: "nbs_viewer",
    "": "nbs_viewer",
    "DEBUG_CATALOG": "nbs_viewer.catalog",
    "DEBUG_PLOTS": "nbs_viewer.plots",
    "DEBUG_RUNLIST": "nbs_viewer.runlist",
    "cache": "nbs_viewer.cache",
    "dimension": "nbs_viewer.dimensions",
    "perf": "perf",
}

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
        Legacy category (e.g., "DEBUG_CATALOG", "dimension"). This is
        mapped into a structured logger name, like ``nbs_viewer.catalog``.
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
                logger.info(f"{function_name} | {end_time - start_time:.6f}s")
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
            logger.info(f"{name} | {end_time - start_time:.6f}s")
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
                logger.info(f"{name} | {end_time - start_time:.6f}s")
                return result

            return wrapper

        return decorator
