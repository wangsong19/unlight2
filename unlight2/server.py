import asyncio
import uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

from functools import partial
import multiprocessing as mp
import signal
from os import kill

from .simple_http import SimpleHttp
from .httproute import HttpRouter
from .lightlog import lightlog

class Server:
    ''' environment of service
        1. uvloop for asynchronous tasks
        2. support multi-process
        3. slots for middlewares(protocol, db, cache, message..)
    '''

    def __init__(self, address, protocol_cls=SimpleHttp):
        self.address = address
        self.protocol_cls = protocol_cls
        self.router = HttpRouter.get_router() # read_only

    def run(self):
        conns = set()
        loop = asyncio.get_event_loop()
        prot_dict = {
                "conns": conns,
                "router": self.router,
                "loop": loop}
        prot_factory = partial(self.protocol_cls, **prot_dict)
        server_task = loop.create_server(prot_factory, *self.address, reuse_port=True)
        server = loop.run_until_complete(server_task)

        # loop signal handler
        def shutdown_handler():
            # close conns
            for conn in conns:
                conn.disconnect()
            # event stop
            loop.stop()
        loop.add_signal_handler(signal.SIGINT, shutdown_handler)
        loop.add_signal_handler(signal.SIGTERM, shutdown_handler)
            
        try:
            loop.run_forever()
        finally:
            loop.close()

    def run_multi_process(self, n=0):
        ''' default use num of cpus as worker-process '''

        if n == 1:
            self.run()
            unlight_logger = lightlog.get_logger(fname="info_unlight2")
            unlight_logger.info(f"server starts {self.address} single-process ..")
        else:
            if not n:
                n = mp.cpu_count()

            workers = []
            # starts worker for log
            log_worker, unlight_logger = lightlog.get_ready_log_worker(fname="info_unlight2")
            workers.append(log_worker)
            log_worker.start()

            # register signals
            def singal_handler(sig, frame):
                for worker in workers:
                    kill(worker.pid, signal.SIGTERM)
            signal.signal(signal.SIGINT, singal_handler)
            signal.signal(signal.SIGTERM, singal_handler)
            
            # starts request workers
            for _ in range(n):
                worker = mp.Process(target=self.run)
                workers.append(worker)
                worker.start()
                
            unlight_logger.info(f"server starts {self.address} multi-process ..")
            # wait
            for worker in workers:
                worker.join()
        unlight_logger.info(f"server shut down. good bye~")
