#
# simple-http协议是简化版的http协议, 仅以支持http作为游戏服务器为目的
#

from os import environ
import re
from asyncio import Protocol
from time import time
from httptools import HttpRequestParser, HttpParserError, parse_url
import traceback
import orjson as json
from datetime import datetime

from log import Unlight2Logger
unlight_logger = Unlight2Logger.get_logger()

class SimpleHttp(Protocol):
    ''' 暂时不处理流(octet-stream)相关的内容
    一次性send/receive所有字节,即暂不支持流
    媒体相关的内容.
    '''

    def __init__(self, *,
            loop,
            conns,
            request_limit_size = 1024*1024*8, # 8M
            request_cur_size = 0,
            request_timeout = 60,   # 消息头解析完时
            response_timeout = 60,  # 开始处理请求时
            is_keep_alive = False,
            keep_alive_timeout = 10 # 一次请求结束时
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

    def data_received(self, data):
        if not self.parser:
            self.parser = HttpRequestParser(self)
        if not self.request:
            self.request = Request(self)

        self.request_cur_size += len(data)
        if self.request_cur_size > self.request_limit_size:
            self.write_error(b"Payload Too Large")

        try:
            self.parser.feed_data(data)
        except HttpParserError:
            self.write_error(b"Bad request")
            traceback.print_exc()

    def connection_lost(self, err):
        ''' 当连接关闭时 '''
        self.conns.discard(self)
        self.cancel_tasks() # 被动清理

        print(">>>> conn is cloesed.")


    ############################# 数据接受与处理
    @property
    def is_keep_alive(self):
        ''' cs端都是keepalive, 此时默认为parser已生成(建立好连接) '''
        return self._is_keep_alive and self.parser.should_keep_alive
    def set_keep_alive(self):
        ''' 启用keep_alive '''
        self._is_keep_alive = True

    def write_response(self, response):
        ''' 返回消息 '''
        try:
            self.transport.write(response)
            print(">>>> send msg: ", response)
        except RuntimeError:
            unlight_logger.error("Connection lost before response written @ %s",
                    self.request.ip if self.request else "Unknown")
        finally:
            if self._is_keep_alive:
                self.tasks.append(
                        self.loop.call_later(self.keep_alive_timeout, self.keep_alive_timeout_handler))
                self.cleanup()
            else:
                self.transport.close()
                self.transport = None
                print(">>>> is_keep_alive is False, transport closed.")

    def write_error(self, err):
        ''' 错误处理 '''
        try:
            self.transport.write(err)
        except RuntimeError:
            unlight_logger.error("Connection lost before error written @ %s",
                    self.request.ip if self.request else "Unknown")
        finally:
            try:
                self.transport.close()
                self.transport = None
            except AttributeError:
                unlight_logger.error("Connection lost before server could close it.")
            return

    def cleanup(self):
        ''' keep_alive清理此次请求, 以用于下次请求 '''
        self.request_cur_size = 0
        self.parser = None
        self.request = None

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
        self.transport.close()
        self.transport = None

        print(">>>> KeepAlive Timeout. Closing connection.")

    ############################# 数据解析(目前暂不处理流相关)
    def on_url(self, burl):
        ''' burl: url bytes '''
        self.request.add_burl(burl)

    def on_header(self, bname, bvalue):
        ''' bname: header name bytes
        bvalue: header value bytes
        '''
        self.request.add_bheader(bname, bvalue)
        if bname.lower() == b"content-length" and int(bvalue) > self.request_limit_size:
            self.write_error(b"Payload Too Large.")
        if bname.lower() == b"expect" and bvalue.lower() == b"100-continue":
            self.write_error(b"HTTP 1.1 \r\n\r\n100-continue\r\n")

    def on_header_complete(self):
        ''' 消息头解析结束,开启返回超时任务 '''
        self.tasks.append(
                self.loop.call_later(self.response_timeout, self.response_timeout_handler))

    def on_body(self, bbody):
        ''' bbody: body bytes '''
        self.request.add_bbody(bbody)

    def on_message_complete(self):
        ''' 消息接受完毕,处理请求 '''
        #request_task = self.loop.create_task(
        #        self.app.handle_request(self.request, response_callback))
        #self.tasks.append(request_task)
        
        # test 写回
        tb = b"HTTP/1.1 200 OK\r\ncontent-type: text/html;charset=utf-8\r\n\r\nhello,I am back!"
        self.write_response(tb)


bkey_pattern = re.compile(rb'name="(.*)"')
bfile_key_pattern = re.compile(rb'name="(.*)";')
bfile_suffix_pattern= re.compile(rb'filename=".*(\..*)";')
class Request:

    def __init__(self, transporter):
        ''' 1. 仅解析utf-8编码(默认)
            2. file仅支持单个文件, 多个文件使用form
        '''
        self.__transporter = transporter
        # 解析前数据
        self.__burl = None
        self.__bheaders = {}
        self.__bbody = None
        # 解析之后的数据
        self.body = None
        self.raw = None
        self.form = None
        self.json = None
        self.file = None

        #self.ctx = None
        self.init_env()

    def init_env(self):
        ''' 初始化局部可用的本地环境(目前仅开放base_dir) '''
        base_dir = environ.get("PWD")
        self.env = {"BASE_DIR": base_dir}

    def add_burl(self, burl):
        ''' url当前解析的参数
            _bschema: 协议
            _bhost: 地址
            _port: 端口
            _bpath: 路径
            _bfragment: 锚点
            _buserinfo: 用户信息(old)
            _bquery_params: 查询参数
        '''
        self.__burl = burl
        # 解析url
        url = parse_url(burl)
        self._bschema= url.schema
        self._bhost = url.host
        self._port = 443 if self._bschema == b"https" else 80
        self._bpath = url.path
        self._bfragment = url.fragment
        self._buserinfo = url.userinfo
        bquery_params = {}
        if url.query:
            qs = url.query.split(b"&")
            for q in qs:
                p, v = q.split(b"=")
                bquery_params[p] = v
        self._bquery_params = bquery_params

    def add_bheader(self, bname, bvalue):
        ''' headers当前解析的参数, 方便后续的处理
            _bhost: 会覆盖url的host(如果有)
            _bconnection: 连接方式(keep_alive/close)
            _bcontent_type: application/text; charset= ..
            _bagent: 代理
            _baccept: 接受mime格式
            _baccept_encoding: 接受压缩格式
            _bcookies: 设置cookies
            _bcache_control: 是否使用缓存
            _bcontent_length: 请求长度
            _bboundary: 表单分割符
        保留处理项:
            1. agent阻止指定agent访问
            2. cache-control是否使用缓存
            3. host跨域
        '''
        bname = bname.strip()
        self.__bheaders[bname] = bvalue
        l_bname = bname.lower()

        if l_bname == b"host":
            self._bhost = bvalue
        elif l_bname == b"connection":
            if bvalue.lower() == b"keep-alive":
                self.__transporter.set_keep_alive()
        elif l_bname == b"content-type":
            self._bcontent_type = bvalue
            if l_bname.find(b"form-data"):
                _, bb = bvalue.split(b";")
                bboundary = bb.split(b"=")[1].strip()
                bboundary = b"--" + bboundary
                self._bboundary = bboundary
        elif l_bname == b"user-agent":
            self._bagent = bvalue
        elif l_bname == b"accept":
            self._baccept = bvalue
        elif l_bname == b"accept-encoding":
            self._baccept_encoding = bvalue
        elif l_bname == b"cookie":
            self._bcookies = bvalue.split(b";")
        elif l_bname == b"cache-control":
            self._bcache_control = bvalue
        elif l_bname == b"content-length":
            self._bcontent_length = bvalue

    def add_bbody(self, bbody):
        ''' 解析消息体:
            1. x-www-form-urlencoded -> self.form + self.raw
            2. form-data             -> self.form
            3. raw(text)             -> self.raw + self.body
            4. raw(json)             -> self.raw + self.json
            5. binary(text)          -> self.files
            6. binary(octect-stream) -> self.files
            7. binary(o-MIME)        -> self.files
        '''
        self.__bbody = bbody
        print(">>>>>> 查看body: ", bbody)
        
        bcontent_type = self._bcontent_type.lower()
        if bcontent_type.find(b"x-www-form-urlencoded") > -1:
            data = bbody.split(b"\r\n\r\n")[1].decode()
            self.raw = data

            items = data.split("&")
            form = {}
            for item in items:
                name, value = item.split("=")
                form[name] = value
            self.form = form
        elif bcontent_type.find(b"form-data") > -1:
            bboundary = self._bboundary
            bdata_list = bbody.split(bboundary)
            form = {}
            for bitem in bdata_list:
                bitem = bitem.strip()
                if bitem and bitem != b"--":
                    if bitem.find(b"\r\n\r\n") > -1:
                        bfdes, bf = bitem.split(b"\r\n\r\n")
                        bkey_list = bfile_key_pattern.findall(bfdes)
                        bsuffix_list = bfile_suffix_pattern.findall(bfdes)
                        if not bkey_list:
                            bkey_list = [str(time()).encode()]
                        if not bsuffix_list:
                            bsuffix_list = [b""]
                        if not bf:
                            self.__transporter.write_error(b"Bad Request.")
                        form[(bkey_list[0]+bsuffix_list[0]).decode()] = bf
                    else:
                        _, bdata = bitem.split(b";")
                        bkey_des, bvalue = bdata.split(b"\r\n\r\n")
                        key = key_pattern.findall(bkey_des)[0].decode()
                        form[key] = bvalue.decode()
            self.form = form
        elif bcontent_type.find(b"text/plain") > -1:
            self.body = self.raw = bbody.decode()
        elif bcontent_type.find(b"json") > -1:
            body = bbody.decode()
            self.body = body
            self.json = json.loads(body)
        elif bcontent_type.find(b"octet-stream") > -1:
            self.body = bbody
            self.file = bbody
        else: # other MIME(no name tag.)
            self.file = bbody
        

    # 读取请求信息(查看时解析)
    # ------------------------
    def get_url(self):
        ''' 查看url '''
        url = ""
        burl = self.__burl
        url = burl.decode()
        return url

    def get_headers(self):
        ''' 查看headers '''
        headers = {}
        bheaders = self.__bheaders
        for bname, bvalue in bheaders.items():
            name = bname.decode()
            value = bvalue.decode()
            headers[name] = value
        return headers

    def get_raw(self):
        return self.raw

    def get_form(self):
        ''' 可以包含多个文件 '''
        return self.form

    def get_json(self):
        return self.json

    def get_file(self):
        ''' 可能包含不完整的文件二进制数据 '''
        return self.file

gmt_format = "%a, %d %b %Y %H:%M:%S GMT"
class Response:

    def __init__(self, version= "1.1", code=200, data=""):
        self.version = version
        self.code = code
        self.headers = {
                "Content-Type": "text/plain;charset=utf-8",
                "Content-Length": 0,
                "Date": datetime.utcnow().strftime(gmt_format)}
        self.data = data

    def update_version(self, version):
        if version > self.version:
            self.version = version

    def get_code_status(self, code):
        return STATUS_CODE_MSG.get(code, "")

    def modify_headers(self, headers={}):
        self.headers.update(headers)

    def encode_headers(self):
        ''' 编码消息头部信息 '''
        headers = ""
        hs = self.headers
        for h, v in hs:
            headers += f"{h}: {v}\r\n"
        headers += "\r\n"
        title = f"HTTP/{self.version} {self.code} {self.get_code_status(self.code)}\r\n"

        return title.encode() + headers.encode()

    def raw(self):
        data = self.data
        if type(data) is not bytes:
            raise TypeError(f"the data of response {data} is not type of bytes.")

        content_type = self.headers.get("Content-Type")
        if content_type != "application/octet-stream":
            raise TypeError(f"content type {content_type} is not suitable for `raw` function.")
        
        return self.encode_headers() + data

    def text(self):
        pass

    def html(self):
        pass

    def json(self):
        pass

    def file(self):
        pass


STATUS_CODE_MSG = {
    100: "Continue",
    101: "Switching Protocols",

    200: "OK",
    201: "Created",
    202: "Accepted",
    203: "Non-Authoritative Information",
    204: "No Content",
    205: "Reset Content",	
    206: "Partial Content",	

    300: "Multiple Choices",
    301: "Moved Permanently",
    302: "Found",
    304: "Not Modified",
    305: "Use Proxy",
    307: "Temporary Redirect",	

    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    407: "Proxy Authentication Required",
    408: "Request Time-out",
    409: "Conflict",
    411: "Length Required",
    412: "Precondition Failed",
    413: "Request Entity Too Large",
    414: "Request-URI Too Large",
    415: "Unsupported Media Type",
    416: "Requested range not satisfiable",
    417: "Expectation Failed",

    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Time-out",
    505: "HTTP Version not supported",
}
