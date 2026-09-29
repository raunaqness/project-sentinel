"""Process-wide logging setup."""

import logging

from sentinel.config import get_settings


def configure_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
