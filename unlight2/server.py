#
# 作为服务器环境运行的抽象环境,主要有以下几个特征
# 1. 异步处理,各个执行流程,loop使用uvloop
# 2. 支持多进程
# 3. 支持协议扩展,例如http,websocket,tcp..
# 4. 为各种类型的任务提供插槽式调用, 包括:
#       数据序列化, 日志, 存储
# 5. 采用中间件的方式在消息上行和下行之间进行独立的处理
# 

import os
from functools import partial
import asyncio
import uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

from log import unlight_logger

class Server:

    def __init__(self, address, protocol, prot_dict={}):
        '''
        address
        protocol
        prot_dict
        '''
        self.address = address
        self.protocol = protocol
        self.prot_dict = prot_dict
        self.loop = asyncio.get_event_loop()
        self.conns = set() # global conns

    def run(self):
        ''' use signal '''
        self.prot_dict.update({"loop": self.loop})
        self.prot_dict.update({"server": self})
        self.prot_dict.update({"conns": self.conns})

        prot_factory = partial(self.protocol, **self.prot_dict)
        server_task = self.loop.create_server(prot_factory, *self.address)
        server = self.loop.run_until_complete(server_task)

        try:
            unlight_logger.info(f"server start {self.address}")
            self.loop.run_forever()
        finally: # temp interrupt
            self.stop()
            self.loop.stop()
            self.loop.close()

    def stop(self):
        for conn in self.conns:
            conn.disconnect()

    async def handle_request(self, request, response_callback):
        tb = b"HTTP/1.1 200 OK\r\nContent-Type: text/html;charset=utf-8\r\nContent-Length:16\r\nConnection: keep-alive\r\nKeep-Alive:10\r\n\r\nhello,I am back!"
        await asyncio.sleep(.1)
        response_callback(tb)
