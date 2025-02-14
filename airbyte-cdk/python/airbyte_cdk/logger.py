#
# Copyright (c) 2021 Airbyte, Inc., all rights reserved.
#

import logging
import logging.config
import traceback
from typing import Tuple

from airbyte_cdk.models import AirbyteLogMessage, AirbyteMessage
from airbyte_cdk.utils.airbyte_secrets_utils import filter_secrets
from deprecated import deprecated

TRACE_LEVEL_NUM = 5

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "airbyte": {"()": "airbyte_cdk.logger.AirbyteLogFormatter", "format": "%(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "airbyte",
        },
    },
    "root": {
        "handlers": ["console"],
    },
}


def init_logger(name: str = None):
    """Initial set up of logger"""
    logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")
    logger = logging.getLogger(name)
    logger.setLevel(TRACE_LEVEL_NUM)
    logging.config.dictConfig(LOGGING_CONFIG)
    return logger


class AirbyteLogFormatter(logging.Formatter):
    """Output log records using AirbyteMessage"""

    # Transforming Python log levels to Airbyte protocol log levels
    level_mapping = {
        logging.FATAL: "FATAL",
        logging.ERROR: "ERROR",
        logging.WARNING: "WARN",
        logging.INFO: "INFO",
        logging.DEBUG: "DEBUG",
        TRACE_LEVEL_NUM: "TRACE",
    }

    def format(self, record: logging.LogRecord) -> str:
        """Return a JSON representation of the log message"""
        message = super().format(record)
        airbyte_level = self.level_mapping.get(record.levelno, "INFO")
        message = filter_secrets(message)
        log_message = AirbyteMessage(type="LOG", log=AirbyteLogMessage(level=airbyte_level, message=message))
        return log_message.json(exclude_unset=True)


def log_by_prefix(msg: str, default_level: str) -> Tuple[int, str]:
    """Custom method, which takes log level from first word of message"""
    valid_log_types = ["FATAL", "ERROR", "WARN", "INFO", "DEBUG", "TRACE"]
    split_line = msg.split()
    first_word = next(iter(split_line), None)
    if first_word in valid_log_types:
        log_level = logging.getLevelName(first_word)
        rendered_message = " ".join(split_line[1:])
    else:
        log_level = logging.getLevelName(default_level)
        rendered_message = msg

    return log_level, rendered_message


@deprecated(version="0.1.47", reason="Use logging.getLogger('airbyte') instead")
class AirbyteLogger:
    def log(self, level, message):
        log_record = AirbyteLogMessage(level=level, message=message)
        log_message = AirbyteMessage(type="LOG", log=log_record)
        print(log_message.json(exclude_unset=True))

    def fatal(self, message):
        self.log("FATAL", message)

    def exception(self, message):
        message = f"{message}\n{traceback.format_exc()}"
        self.error(message)

    def error(self, message):
        self.log("ERROR", message)

    def warn(self, message):
        self.log("WARN", message)

    def info(self, message):
        self.log("INFO", message)

    def debug(self, message):
        self.log("DEBUG", message)

    def trace(self, message):
        self.log("TRACE", message)
