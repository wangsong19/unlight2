#
# 作为服务器环境运行的抽象环境,主要有以下几个特征
# 1. 异步处理,各个执行流程,loop使用uvloop
# 2. 支持多进程
# 3. 为各种类型的任务提供插槽式调用, 包括:
#       数据序列化, 日志, 存储
# 

import os
from functools import partial
import asyncio
import uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

from log import unlight_logger
from httproute import HttpRouter

class Server:

    def __init__(self, address, protocol_cls, prot_dict={}):
        self.address = address
        self.protocol_cls = protocol_cls
        self.prot_dict = prot_dict
        self.loop = asyncio.get_event_loop()
        self.conns = set()
        self.router = HttpRouter.get_router()

    def run(self):
        self.prot_dict.update({"loop": self.loop})
        self.prot_dict.update({"conns": self.conns})
        self.prot_dict.update({"router": self.router})

        prot_factory = partial(self.protocol_cls, **self.prot_dict)
        server_task = self.loop.create_server(prot_factory, *self.address)
        server = self.loop.run_until_complete(server_task)

        try:
            unlight_logger.info(f"server start {self.address}")
            self.loop.run_forever()
        except KeyboardInterrupt:
            unlight_logger.info(f"server close. bye ~")
        finally: # interrupt
            self.stop()
            self.loop.stop()
            self.loop.close()

    def stop(self):
        for conn in self.conns:
            conn.disconnect()

    async def handle_request(self, request, response):
        await asyncio.sleep(0.01) # will call async func
        response.json({"name": "wangsong"})


class App:

    ''' User App
    1. multi-process server instance
    2. bind router server for request
    '''

    def __init__(self, address, work_num=1):
        pass
