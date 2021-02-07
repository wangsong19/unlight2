import multiprocessing
import time
import signal

import log


def test_ten():
    logger = log.get_logger(queue, "unlight2_log")
    i = 0
    while True:
        if i > 120: break
        time.sleep(1)
        logger.info("--- you have a new log message, please record it!", i)
        i += 1


if __name__ == "__main__":
    queue = multiprocessing.Queue(10)

    worker1 = multiprocessing.Process(target=log.process_logger, args=(queue,))
    worker1.start()
    worker2 = multiprocessing.Process(target=test_ten)
    worker2.start()

    def handler(sig, f):
        worker1.kill()
        worker2.kill()
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    worker1.join()
    
