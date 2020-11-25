import log

logger = log.UnLogger.get_base_logger()
logger.debug("Hello, This is debug message!")
logger.info("Hello, This is info message!")
logger.warning("Hello, This is warning message!")
logger.error("Hello, This is error message!")
logger.fatal("Hello, This is fatal message!")
