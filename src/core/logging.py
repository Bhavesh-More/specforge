"""Structured logging configuration for SpecForge."""

import sys
from functools import lru_cache
import logging

import structlog
from structlog import BoundLogger
from structlog.types import Processor

from src.core.config import get_config

# Module-level version, injected at packaging time
__version__ = "0.1.0"


def _get_processors(debug: bool) -> list[Processor]:
    """Build the structlog processor chain.

    Args:
        debug: If True, use colored console output; otherwise JSON.
    """
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if debug:
        processors.extend([
            structlog.dev.ConsoleRenderer(colors=True),
        ])
    else:
        processors.extend([
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ])

    return processors


def _configure_structlog(debug: bool) -> None:
    processors = _get_processors(debug)

    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, get_config().log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, get_config().log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


@lru_cache
def get_logger(name: str) -> BoundLogger:
    """Return a configured structlog BoundLogger for the given name.

    The logger has ``service="specforge"`` and ``version`` bound
    in all log entries.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A BoundLogger with bound context vars.
    """
    try:
        cfg = get_config()
    except Exception:
        cfg = None

    debug_mode = cfg.debug if cfg else False
    _configure_structlog(debug=debug_mode)

    log = structlog.get_logger(name)
    log = log.bind(service="specforge", version=__version__)
    return log
