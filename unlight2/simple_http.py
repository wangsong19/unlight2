#
# simple-http协议是简化版的http协议, 仅以支持http作为游戏服务器为目的
#

from os import environ
from asyncio import Protocol
from time import time
from httptools import HttpRequestParser, HttpParserError

import traceback

class SimpleHttp(Protocol):
    ''' 暂时不处理流(octet-stream)相关的内容
    一次性send/receive所有字节,即暂不支持流
    媒体相关的内容.
    '''

    def __init__(self, *,
            loop,
            conns,
            request_limit_size = 1024*4,
            request_cur_size = 0,
            request_timeout = 60,   # 消息头解析完时
            response_timeout = 60,  # 开始处理请求时
            is_keep_alive = False,
            keep_alive_timeout = 60 # 一次请求结束时
            ):

        self.loop = loop
        self.transport = None
        self.parser = None
        self.request = None
        self.response = None

        self.request_limit_size= request_limit_size
        self.request_cur_size = 0
        self.request_timeout = request_timeout
        self.response_timeout = response_timeout
        self._is_keep_alive = is_keep_alive
        self.keep_alive_timeout = keep_alive_timeout
        self.last_request_time = None

        self.conns = conns
        self.tasks = []

    ############################# conn base
    def connection_made(self, transport):
        self.transport = transport
        remote_addr = transport.get_extra_info("peername") # tuple (ip, port)
        self.remote_addr = remote_addr
        self.conns.add(self)

        self.last_request_time = time()
        # 请求超时处理
        self.tasks.append(
                self.loop.call_later(self.request_timeout, self.request_timeout_handler))
        print(">>>>>>> connection_made", remote_addr)

    def data_received(self, data):
        if not self.parser:
            self.parser = HttpRequestParser(self)
        if not self.request:
            self.request = Request(self.remote_addr)

        self.request_cur_size += len(data)
        if self.request_cur_size > self.request_limit_size:
            self.write_error(b"Payload Too Large")

        print(">>>>>>> data_received", data)
        try:
            self.parser.feed_data(data)
        except HttpParserError:
            self.write_error(b"Bad request")
            traceback.print_exc()

    def connection_lost(self, err):
        ''' 当连接关闭时 '''
        if err:
            print(err)
        print("conn is cloesed.")
        
        self.conns.discard(self)
        self.cancel_tasks() # 被动清理


    ############################# 数据接受与处理
    @property
    def is_keep_alive(self):
        ''' cs端都是keepalive, 此时默认为parser已生成(建立好连接) '''
        assert self.parser
        return self._is_keep_alive and self.parser.should_keep_alive

    def write_response(self, response):
        ''' 返回消息 '''
        try:
            self.transport.write(response)
            print("写回了消息: ", response.decode())
        except RuntimeError:
            print("Connection lost before response written @ %s",
                    self.request.ip if self.request else "Unknown")
        finally:
            if self._is_keep_alive:
                self.tasks.append(
                        self.loop.call_later(self.keep_alive_timeout, self.keep_alive_timeout_handler))
                self.cleanup()
            else:
                print("没有设置keep_alive, 将自动关闭....")
                self.transport.close()
                self.transport = None

    def write_error(self, err):
        ''' 错误处理 '''
        try:
            self.transport.write(err)
        except RuntimeError:
            print("Connection lost before error written @ %s",
                    self.request.ip if self.request else "Unknown")
        finally:
            try:
                self.transport.close()
                self.transport = None
            except AttributeError:
                print("Connection lost before server could close it.")

    def cleanup(self):
        ''' keep_alive清理此次请求, 以用于下次请求 '''
        self.request_cur_size = 0
        self.parser = None
        self.request = None
        self.cancel_tasks()

    def cancel_tasks(self):
        ''' 清理任务: 出错时/结束时 '''
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()

    def disconnect(self):
        ''' 主动关闭连接 '''
        self.transport.close()
        self.transport = None

    def request_timeout_handler(self):
        ''' 请求超时处理:开始接受数据时开始call_later '''
        self.cancel_tasks()
        self.write_error(b"Request Timeout.")

    def response_timeout_handler(self):
        ''' 返回超时处理:接受完数据开始call_later '''
        self.cancel_tasks()
        self.write_error(b"Response Timeout.")

    def keep_alive_timeout_handler(self):
        ''' keep_alive:返回结果后开始call_later '''
        self.cancel_tasks()
        print("KeepAlive Timeout. Closing connection.")
        self.transport.close()
        self.transport = None

    ############################# 数据解析(目前暂不处理流相关)
    def on_url(self, burl):
        ''' burl: url bytes '''
        print(">>> checkout burl: ", burl)

        self.request.add_burl(burl)

    def on_header(self, bname, bvalue):
        ''' bname: header name bytes
        bvalue: header value bytes
        '''
        print(">>> checkout bname, bvalue: ", bname, bvalue)

        self.request.add_bheader(bname, bvalue)
        if bname.lower() == b"content-length" and int(bvalue) > self.request_limit_size:
            self.write_error(b"Payload Too Large.")
        if bname.lower() == b"expect" and bvalue.lower() == b"100-continue":
            self.write_error(b"HTTP 1.1 \r\n\r\n100-continue\r\n")

    def on_header_complete(self):
        ''' 消息头解析结束,开启返回超时任务
        '''
        print(">>> checkout headers analyse done.")

        self.tasks.append(
                self.loop.call_later(self.response_timeout, self.response_timeout_handler))

    def on_body(self, bbody):
        ''' bbody: body bytes'''
        print(">>> checkout bbody: ", bbody)

        self.request.add_bbody(bbody)

    def on_message_complete(self):
        ''' 消息接受完毕,处理请求 '''
        print(">>> checkout message complete >> handle this request.")

        #request_task = self.loop.create_task(
        #        self.app.handle_request(self.request, response_callback))
        #self.tasks.append(request_task)
        
        # test 写回
        tb = b"HTTP/1.1 200 OK\r\nContent-Type: text/html;charset=utf-8\r\n\r\nhello,I am back!"
        self.write_response(tb)


class Request:

    def __init__(self, remote_addr):
        ''' 当处理流时,考虑body使用[]
        '''
        self.remote_addr = remote_addr
        # 解析前数据
        self.__burl = None
        self.__bheaders = {}
        self.__bbody = None
        # 解析之后的数据
        self.raw = None
        self.form = None
        self.json = None
        self.file = None

        #self.ctx = None
        self.init_env()

    def init_env(self):
        ''' 初始化局部可用的本地环境
        (目前仅开放base_dir)
        '''
        base_dir = environ.get("PWD")
        self.env = {
            "BASE_DIR": base_dir
        }

    def add_burl(self, burl):
        self.__burl = burl

        print("---------- 查看url")
        self.get_url()

    def add_bheader(self, bname, bvalue):
        ''' 部分消息头对应多个字段 '''
        self.__bheaders[bname] = bvalue

        print("---------- 查看headers")
        self.get_headers()

    def add_bbody(self, bbody):
        ''' 暂不支持追加流 '''
        self.__bbody = bbody
        
        print("---------- 查看body")
        self.get_raw()

    # 读取请求信息(查看时解析)
    # ------------------------
    def get_url(self):
        ''' 查看url '''
        url = ""
        burl = self.__burl
        try:
            url = burl.decode()
        except UnicodeDecodeError:
            url = burl.decode("latin-1")
        print("转换之后的url::::: ", url)
        return url

    def get_headers(self):
        ''' 查看headers '''
        headers = {}
        bheaders = self.__bheaders
        try:
            for bname, bvalue in bheaders.items():
                name = bname.decode()
                value = bvalue.decode()
                headers[name] = value
        except UnicodeDecodeError:
            for bname, bvalue in bheaders.items():
                name = bname.decode("latin-1")
                value = bvalue.decode("latin-1")
                headers[name] = value
        print("转换之后的headers::::: ", headers)
        return headers

    def get_raw(self):
        ''' 查看请求体(通用格式) '''
        if not self.raw:
            raw = ""
            bbody = self.__bbody
            try:
                raw = bbody.decode()
            except UnicodeDecodeError:
                raw = bbody.decode("latin-1")
            self.raw = raw
        print("转换之后的raw::::: ", raw)
        return self.raw

    def get_form(self):
        ''' 查看请求体(表单) '''
