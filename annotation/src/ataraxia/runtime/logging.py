"""Configure only Ataraxia's logger; never log environment or API key values."""
import logging


def get_logger():
    logger = logging.getLogger("ataraxia")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
