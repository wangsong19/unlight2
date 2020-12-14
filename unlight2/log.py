import logging
from logging.handlers import TimedRotatingFileHandler

class Unlight2Logger:
    ''' 默认条件:
    1. 循环日志(按天)
    2. 提供基础logger获取管理'''

    loggers = {}
    name = "unlinght2.log"
    fmt = "[%(levelname)s][%(asctime)s] %(message)s"
    detail_fmt = "[%(levelname)s][%(asctime)s][pid:%(process)d][tid:%(thread)d] --%(funcName)s-- %(message)s"

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

        tmp_logger = cls.loggers.get("tmp_logger")
        if not tmp_logger:
            f = cls.fmt
            logger = MyLogger(cls.name)
            logger.setLevel(level)

            formatter = logging.Formatter(f)
            c_handler = logging.StreamHandler()
            c_handler.setFormatter(formatter)
            logger.addHandler(c_handler)

            tmp_logger = logger
            cls.loggers["tmp_logger"] = tmp_logger

        return tmp_logger

    def build_logger(self, f, file_name, backupCount, level=logging.INFO):
        ''' 构建日志打印 '''

        logger = self.loggers.get(file_name)
        if not logger:
            logger = MyLogger(self.name)
            logger.setLevel(level)
            formatter = logging.Formatter(f)

            c_handler = logging.StreamHandler()
            c_handler.setFormatter(formatter)
            c_handler.encoding = "utf-8"
            logger.addHandler(c_handler)

            f_handler = TimedRotatingFileHandler(file_name, when="D", backupCount=backupCount)
            f_handler.setFormatter(formatter)
            f_handler.encoding = "utf-8"
            logger.addHandler(f_handler)

            self.loggers[file_name] = logger

        return logger

    @classmethod
    def shutdown(cls):
        ''' 停服时关闭日志系统 '''
        logging.shutdown

    
class MyLogger(logging.Logger):
    
    ''' 习惯化logger的message打印方式 
    debug, info, warning, error, fatal'''

    def __init__(self, name):
        super(MyLogger, self).__init__(name)
    
    def debug(self, *args):
        super().debug(" ".join(args))

    def info(self, *args):
        super().info(" ".join(args))

    def warning(self, *args):
        super().warning(" ".join(args))

    def error(self, *args):
        super().error(" ".join(args))

    def fatal(self, *args):
        super().fatal(" ".join(args))


unlight_logger = Unlight2Logger.get_logger()
