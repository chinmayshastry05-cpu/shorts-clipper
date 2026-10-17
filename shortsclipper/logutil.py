"""Stage-prefixed logging (one logger per pipeline stage)."""

import logging
import sys

_VERBOSE = False


def get_logger(name):
    logger = logging.getLogger(f"shortsclipper.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s",
                                               datefmt="%H:%M:%S"))
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if _VERBOSE else logging.INFO)
    logger.propagate = False
    return logger


def set_verbose(verbose):
    global _VERBOSE
    _VERBOSE = bool(verbose)
    for name in list(logging.root.manager.loggerDict):
        if name.startswith("shortsclipper."):
            logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.INFO)
