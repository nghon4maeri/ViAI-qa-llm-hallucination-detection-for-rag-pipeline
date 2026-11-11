# backend/app/core/logging.py
import sys
import logging

try:
    from loguru import logger as _loguru_logger
    _HAS_LOGURU = True
except ImportError:
    _HAS_LOGURU = False

def get_logger(name: str = "viai_qa"):
    if _HAS_LOGURU:
        return _loguru_logger
    return logging.getLogger(name)

logger = get_logger()
