import log
import threading
import time

logger = log.UnLogger.get_tmp_logger()
logger.debug("Hello, This is debug message!")
logger.info("Hello, This is info message!")
logger.warning("Hello, This is warning message!")
logger.error("Hello, This is error message!")
logger.fatal("Hello, This is fatal message!")

flogger = log.UnLogger.get_logger()
flogger.debug("Hello, This is file debug message!")
flogger.info("Hello, This is file info message!")
flogger.warning("Hello, This is file warning message!")
flogger.error("Hello, This is file error message!")
flogger.fatal("Hello, This is file fatal message!")

def test_rodtating_logger():
    sub = threading.Thread(target=print_file, args=())
    sub.start()
    sub.join()
    
def print_file():
    # 测试时设置rotating的when参数为'S',默认是不允许修改的
    flogger = log.UnLogger.get_detail_logger()
    t1 = time.time()
    t2 = time.time()
    while t2 - t1 < 10:
        time.sleep(0.2)
        flogger.info("record one message in the file(console). %f" % time.time())
        t2 = time.time()

test_rodtating_logger()
