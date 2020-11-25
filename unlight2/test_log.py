import log
import threading
import time
import unittest

class UnLoggerTest(unittest.TestCase):

    @unittest.skip("ignore")
    def test_tmp_logger(self):
        logger = log.Unlight2Logger.get_tmp_logger()
        logger.debug("Hello, This is debug message!", "second arg")
        logger.info("Hello, This is info message!", "second arg")
        logger.warning("Hello, This is warning message!", "second arg")
        logger.error("Hello, This is error message!", "second arg")
        logger.fatal("Hello, This is fatal message!", "second arg")

    def test_logger(self):
        flogger = log.Unlight2Logger.get_logger()
        flogger.debug("Hello, This is file debug message!")
        flogger.info("Hello, This is file info message!")
        flogger.warning("Hello, This is file warning message!")
        flogger.error("Hello, This is file error message!")
        flogger.fatal("Hello, This is file fatal message!")

    @unittest.skip("ignore")
    def test_rodtating_logger(self):
        sub = threading.Thread(target=self.print_file, args=())
        sub.start()
        sub.join()
        
    @unittest.skip("ignore")
    def print_file(self):
        # 测试时设置rotating的when参数为'S',默认是不允许修改的
        flogger = log.Unlight2Logger.get_detail_logger()
        t1 = time.time()
        t2 = time.time()
        while t2 - t1 < 10:
            time.sleep(0.2)
            flogger.info("record one message in the file(console). %f" % time.time())
            t2 = time.time()
