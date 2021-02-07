''' log
multi-processing log tasks.
1. send record to local log process and save it as local file log.
2. send record to log server and save it in log server disk.
---------------------------------------------------------------
usage:
    a. specific `DEFAULT_LOG_CONFIG` configurations
        *fill address when we use log server, and `python log.py`
        on log server, it will listen specific port to work,
        *if address is (), unlight2 will start log process as dae-
        mon process to save records on local disk.
    b. happy to use it.
'''

from os import (
        getcwd as osgetcwd,
        path as ospath, 
        access as osaccess, 
        W_OK as osW_OK)
from sys import (
        stdout,
        stderr)
import logging
from logging.handlers import (
        QueueHandler, 
        SocketHandler, 
        TimedRotatingFileHandler)
from socketserver import (
        StreamRequestHandler,
        ThreadingTCPServer,
        ForkingTCPServer)
from struct import unpack as sunpack
from pickle import loads as ploads


DEFAULT_LOG_CONFIG = {
    # log file name
    "fname": "unlight2",
    # file path dir(use local server)
    "dir": osgetcwd(),
    # default level
    "level": logging.INFO,
    # rotating by when(default "Day")
    "when": "D",
    # backup by week
    "backup_count": 7,
    # use detail log or not
    "is_detail": False,
    # log record formatter
    "fmt": "%(asctime)s[%(levelname)s] %(message)s",
    # log record detail formatter
    "dfmt": "%(asctime)s[%(levelname)s][pid:%(process)d][tid:%(thread)d] %(message)s",
    # use log server > address: ("localhost", 9939)
    "address": (),
}

if DEFAULT_LOG_CONFIG.get("address"):
    import warnings
    address = DEFAULT_LOG_CONFIG["address"]
    warnings.warn(f"you are using {address} as log server to save log files, 
            please ensure that you have set up log server on {address[0]}")

def get_logger(fname=DEFAULT_LOG_CONFIG["fname"], is_detail=False, queue=None):
    ''' get a specific file output record logger 
    fname: output path file name
    is_detail: record formats as detial or not
    '''
    return Logger(fname, is_detail, queue)

def process_logger(queue):
    ''' used in local log process and process safe. e.g.
        log_worker = multiprocessing.Process(
                target=process_logger, args=(queue,), daemon=True)
        log_worker.start()
        log_worker.join()
    '''
    while True:
        try:
            record = queue.get()
            if record is None:
                break
            logger = logging.getLogger(record.name)
            if not logger.handlers:
                handler = TimedRotatingFileHandler(
                            record.name,
                            when=DEFAULT_LOG_CONFIG["when"],
                            backupCount=DEFAULT_LOG_CONFIG["backup_count"])
                logger.addHandler(handler)
            logger.handle(record)
        except Exception:
            import traceback
            print('--unlight2-- log err:', file=stderr)
            traceback.print_exc(file=stderr)


class Logger:
    ''' log client
    0. no queue: single process server, records files local(default)
    1. use queue: multi-process server, records files local by log process
    2. no address: single/multi-process server, records files remote server
    '''
    queue = None

    def __init__(self, fname, is_detail, queue=None):
        Logger.queue = queue
        dir_ = DEFAULT_LOG_CONFIG["dir"]
        if not (ospath.isdir(dir_) 
                or osaccess(dir_, osW_OK)):
            raise FileExistsError(f"logger dir {dir_} is not exists or is not writable")

        serve_address = DEFAULT_LOG_CONFIG["address"]
        level = DEFAULT_LOG_CONFIG["level"]
        fmt = DEFAULT_LOG_CONFIG["dfmt"] \
                if is_detail else DEFAULT_LOG_CONFIG["fmt"]

        # build logger
        logger = logging.Logger(fname)
        logger.setLevel(level)
        formatter = logging.Formatter(fmt)
        # to console
        console = logging.StreamHandler(stdout)
        console.setFormatter(formatter)
        # to file
        if serve_address: # use remote log server
            handler = SocketHandler(*serve_address)
        elif Logger.queue: # use local log process
            handler = QueueHandler(Logger.queue)
        else: # simple log
            handler = TimedRotatingFileHandler(
                    fname,
                    when=DEFAULT_LOG_CONFIG["when"],
                    backupCount=DEFAULT_LOG_CONFIG["backup_count"])
        #handler.encoding = "utf-8" # support utf8
        handler.setFormatter(formatter)
        logger.addHandler(console)
        logger.addHandler(handler)
        self.logger = logger

    def set_level(self, level=logging.INFO):
        self.logger.setLevel(level)

    def debug(self, *args):
        self.logger.debug(" ".join([str(v) for v in args]))

    def info(self, *args):
        self.logger.info(" ".join([str(v) for v in args]))

    def warning(self, *args):
        self.logger.warning(" ".join([str(v) for v in args]))

    def error(self, *args):
        self.logger.error(" ".join([str(v) for v in args]))


''' log server
    RecordStreamHandler: to handle record stream
    RecordReceiver: multi-threading noblock server
    RecordReceiverFork: multi-processing noblock server(only Unix)
'''
class RecordStreamHandler(StreamRequestHandler):
    
    def handle(self):
        while True:
            chunk = self.connection.recv(4)
            if len(chunk) < 4:
                break
            slen = sunpack('>L', chunk)[0]
            chunk = self.connection.recv(slen)
            while len(chunk) < slen:
                chunk = chunk + self.connection.recv(slen-len(chunk))

            record = self.unpickle(chunk)
            logger = logging.getLogger(record.name)
            if not logger.handlers:
                if DEFAULT_LOG_CONFIG.get("is_detail"):
                    formatter = logging.Formatter(DEFAULT_LOG_CONFIG["dfmt"])
                else:
                    formatter = logging.Formatter(DEFAULT_LOG_CONFIG["fmt"])
                handler = TimedRotatingFileHandler(
                            record.name,
                            when=DEFAULT_LOG_CONFIG["when"],
                            backupCount=DEFAULT_LOG_CONFIG["backup_count"])
                handler.setFormatter(formatter)
                logger.addHandler(handler)
            logger.handle(record)

    def unpickle(self, chunk):
        # python issue #14436! we should received record as dict
        # and we should add formatter for server log!
        dict_ = ploads(chunk) # !to dict!
        dict_["level"] = getattr(logging, dict_["levelname"])
        return logging.LogRecord(**dict_)
        
class RecordReceiver(ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, 
            host,
            port,
            handler=RecordStreamHandler):
        ThreadingTCPServer.__init__(self, (host, port), handler)
        self.stop = 0
        self.timeout = 3
    
    def serve_until_stopped(self):
        import select
        stop = 0
        while not stop:
            rd, wr, ex = select.select([self.socket.fileno()], [], [], self.timeout)
            if rd: self.handle_request()
            stop = self.stop
    def shutdown(self):
        self.server_close()
        self.stop = 1

class RecordReceiverFork(ForkingTCPServer):
    allow_reuse_address = True

    def __init__(self, 
            host,
            port,
            handler=RecordStreamHandler):
        ForkingTCPServer.__init__(self, (host, port), handler)
        self.stop = 0
        self.timeout = 3
    
    def serve_until_stopped(self):
        import select
        stop = 0
        while not stop:
            rd, wr, ex = select.select([self.socket.fileno()], [], [], self.timeout)
            if rd: self.handle_request()
            stop = self.stop

    def shutdown(self):
        self.server_close()
        self.stop = 1

class LogServer:
                      
    @classmethod
    def run(cls, address, is_posix=False, is_detail=False):
        level = DEFAULT_LOG_CONFIG.get("level")
        is_detail = DEFAULT_LOG_CONFIG.get("is_detail")
        fmt = DEFAULT_LOG_CONFIG.get("dfmt") \
                if is_detail else DEFAULT_LOG_CONFIG.get("fmt")

        logger = logging.getLogger()
        logger.setLevel(level)
        console = logging.StreamHandler(stdout)
        formatter = logging.Formatter(fmt)
        console.setFormatter(formatter)
        logger.addHandler(console)
        logger.info(f"log server start {address}...") 

        try:
            if is_posix:
                tcpserver = RecordReceiverFork(*address)
            else:
                tcpserver = RecordReceiver(*address)
            tcpserver.serve_until_stopped()
        except KeyboardInterrupt:
            pass
        finally:
            logger.info("log server shutdown .. good bye~")
            tcpserver.server_close()

# starts as server
if __name__ == "__main__":
    address = DEFAULT_LOG_CONFIG.get("address")
    if not address:
        print("--LogServer-- \n` DEFAULT_LOG_CONFIG.address ` is empty!")
    else:
        LogServer.run(address)
