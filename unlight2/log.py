import logging
from logging.handlers import TimedRotatingFileHandler

class UnLogger:
    ''' 默认条件:
    1. 循环日志(按天)
    2. 双向输出: stdout/stderr, file'''

    name = "unlinght2.log"
    fmt = "[%(levelname)s][%(asctime)s] %(message)s"
    detail_fmt = "[%(levelname)s][%(asctime)s][%(process)d][%(thread)d] --%(funcName)s-- %(message)s"

    def __init__(self):
        raise NotImplementedError("Unlight2's log is not Implemented, use `get_logger` instead.")

    @classmethod
    def get_logger(cls, file_name="unlight2.log", backupCount=7):
        ''' 基础日志(console+file) '''
        f = cls.fmt
        return cls.build_logger(cls, f, file_name, backupCount)

    @classmethod
    def get_detail_logger(cls, file_name="unlight2.log", backupCount=7):
        ''' 详细日志(console+file) '''
        f = cls.detail_fmt
        return cls.build_logger(cls, f, file_name, backupCount, logging.DEBUG)

    @classmethod
    def get_tmp_logger(cls, level=logging.DEBUG):
        ''' 临时日志 '''
        f = cls.fmt
        logger = logging.getLogger(cls.name)
        logger.setLevel(level)

        formatter = logging.Formatter(f)
        c_handler = logging.StreamHandler()
        c_handler.setFormatter(formatter)
        logger.addHandler(c_handler)

        return logger

    def build_logger(self, f, file_name, backupCount, level=logging.INFO):
        ''' 构建日志打印 '''
        logger = logging.getLogger(self.name)
        logger.setLevel(level)
        formatter = logging.Formatter(f)

        c_handler = logging.StreamHandler()
        c_handler.setFormatter(formatter)
        logger.addHandler(c_handler)
        f_handler = TimedRotatingFileHandler(file_name, when="D", backupCount=backupCount)
        f_handler.setFormatter(formatter)
        logger.addHandler(f_handler)

        return logger

    @classmethod
    def shutdown(cls):
        ''' 停服时关闭日志系统 '''
        logging.shutdown
