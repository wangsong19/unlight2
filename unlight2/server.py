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
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except:
    print("warning: main loop is not uvloop, try use 'pip install -U uvloop'")

class Server:

    def __init__(self, address, protocol, prot_dict={}):
        '''
        address: 服务地址
        protocol: 协议
        prot_dict: 协议参数
        '''
        self.address = address
        self.protocol = protocol
        self.prot_dict = prot_dict
        self.loop = asyncio.get_event_loop()
        self.conns = set() # 全局连接管理

    def run(self):
        ''' 信号管理停服任务(便于扩展多进程)
        '''
        self.prot_dict.update({"loop": self.loop})
        self.prot_dict.update({"conns": self.conns})

        prot_factory = partial(self.protocol, **self.prot_dict)
        server_task = self.loop.create_server(prot_factory, *self.address)
        server = self.loop.run_until_complete(server_task)

        try:
            print("start server as host: %s:%d"%self.address)
            self.loop.run_forever()
        finally: # 暂时用interrupt来处理
            self.loop.stop()
            self.loop.close()


    def stop(self):
        ''' 关闭
        1. 取消所有连接(连接取消自己的所有任务) 
        2. 关闭loop'''
        for conn in self.conns:
            conn.disconnect()
