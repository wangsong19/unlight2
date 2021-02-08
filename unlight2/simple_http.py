import re
from asyncio import Protocol
from time import time
from httptools import HttpRequestParser, HttpParserError, parse_url
import traceback
import orjson as json
from datetime import datetime

from .exception import UnlightException
from .lightlog import lightlog
unlight_logger = lightlog.get_logger("unlight2")


class SimpleHttp(Protocol):
    ''' 
    simple-http protocol is a light http protocol,
    you can set proxy or gateway for it 
    '''

    __slots__ = (
        "loop",
        "conns",
        "router",
        "transport",
        "request",
        "response",
        "parser",
        "request_limit_size",
        "request_cur_size",
        "request_timeout",
        "response_timeout",
        "keep_alive",
        "last_request_time",
        "remote_addr",
        "request_timeout_task",
        "response_timeout_task",
        "conn_timeout_task"
    )

    def __init__(self, *,
            loop,
            conns,  # server.conns
            router, # path handler mgr
            request_limit_size = 1024*1024*1, # 1M
            request_timeout = 60,
            response_timeout = 60,
            keep_alive = 10):

        self.loop = loop
        self.conns = conns
        self.router = router
        self.transport = None
        self.request = Request(self)
        self.response = Response(self)
        self.response.set_keep_alive()
        self.parser = HttpRequestParser(self)

        self.request_limit_size = request_limit_size
        self.request_cur_size = 0
        self.request_timeout = request_timeout
        self.response_timeout = response_timeout
        self.keep_alive = keep_alive
        self.last_request_time = 0

        self.remote_addr = None
        self.request_timeout_task = None
        self.response_timeout_task = None
        self.conn_timeout_task = None

        self.route_mgr = None

    def connection_made(self, transport):
        self.transport = transport
        self.remote_addr = transport.get_extra_info("peername")
        self.conns.add(self)

        self.last_request_time = time()
        self.request_timeout_task = self.loop.call_later(self.request_timeout, self.request_timeout_handler)

    def data_received(self, data):
        self.request_cur_size += len(data)
        if self.request_cur_size > self.request_limit_size:
            self.response.error(UnlightException(413))

        try:
            self.parser.feed_data(data)
        except HttpParserError:
            self.response.error(UnlightException(401))
            traceback.print_exc()

    def connection_lost(self, err):
        self.conns.discard(self)
        self._cancel_request_timeout_task()
        self._cancel_response_timeout_task()
        self._cancel_conn_timeout_task()

    @property
    def is_keep_alive(self):
        return self.keep_alive and self.parser.should_keep_alive

    def write(self, enc_data):
        ''' write and try keep alive '''
        try:
            self.transport.write(enc_data)
        except RuntimeError:
            unlight_logger.error("Connection lost before response written @ %s",
                    self.remote_addr if self.remote_addr else "Unknown")
        finally:
            if self.is_keep_alive:
                self._cancel_conn_timeout_task()
                self.conn_timeout_task = self.loop.call_later(self.keep_alive, self.keep_alive_timeout_handler)
                self.reset()
            else:
                self.transport.close()
                self.transport = None

    def fatal(self, enc_err):
        ''' wirte and close '''
        try:
            self.transport.write(enc_err)
        except RuntimeError:
            unlight_logger.error("Connection lost before error written @ %s",
                    self.remote_addr if self.remote_addr else "Unknown")
        finally:
            try:
                self.transport.close()
                self.transport = None
            except AttributeError:
                unlight_logger.error("Connection lost before server could close it.")

    def reset(self):
        self.request_cur_size = 0
        self.request.reset()
        self.response.reset()
        self._cancel_response_timeout_task()

    def request_timeout_handler(self):
        self._cancel_request_timeout_task()
        self.response.error(UnlightException(408))

    def response_timeout_handler(self):
        self._cancel_response_timeout_task();
        self.response.error(UnlightException(502))

    def keep_alive_timeout_handler(self):
        self._cancel_request_timeout_task()
        self.transport.close()
        self.transport = None

    def _cancel_request_timeout_task(self):
        if self.request_timeout_task:
            self.request_timeout_task.cancel()
            self.request_timeout_task = None

    def _cancel_response_timeout_task(self):
        if self.response_timeout_task:
            self.response_timeout_task.cancel()
            self.response_timeout_task = None

    def _cancel_conn_timeout_task(self):
        if self.conn_timeout_task:
            self.conn_timeout_task.cancel()
            self.conn_timeout_task = None

    def on_url(self, burl):
        self.request.add_burl(burl)

    def on_header(self, bname, bvalue):
        self.request.add_bheader(bname, bvalue)
        if bname.lower() == b"content-length" and int(bvalue) > self.request_limit_size:
            self.response.error(UnlightException(413))
        if bname.lower() == b"expect" and bvalue.lower() == b"100-continue":
            self.response.error(UnlightException(100))

    def on_header_complete(self):
        self.response_timeout_task = self.loop.call_later(self.response_timeout, self.response_timeout_handler)
        self._cancel_request_timeout_task()

    def on_body(self, bbody):
        if self.request.add_bbody(bbody) == 2:
            self.response.error(UnlightException(400)) # parse err

    def on_message_complete(self):
        self.request.set_method(self.parser.get_method().decode())
        self.loop.create_task(
                    self.router.handle_request(self.request, self.response))


bkey_pattern = re.compile(rb'name="(.*)"$')
bfile_pattern = re.compile(rb'name="(.*)";')     # as file rename
bfile_pattern2 = re.compile(rb'filename="(.*)"') # file real name
class Request:
    __slots__ = (
        "__protocol",
        "__burl",
        "__bheaders",
        "__bbody",
        "method",
        "_bschema",
        "_bhost",
        "_port",
        "_bpath",
        "_bfragment",
        "_buserinfo",
        "_bquery_params",
        "_bconnection",
        "_bcontent_type",
        "_bagent",
        "_baccept",
        "_baccept_encoding",
        "_bcookies",
        "_bcache_control",
        "_bcontent_length",
        "_bboundary",
        "raw",
        "form",
        "json",
        "file",
        "env" # stash
    )

    def __init__(self, protocol):
        ''' 1. utf-8 (default) '''
        self.__protocol = protocol
        self.reset()
    
    def reset(self):
        # bytes
        self.__burl = None
        self.__bheaders = {}
        self.__bbody = None
        # detail byte fields
        self._bschema = None # from url
        self._bhost = None
        self._port = None
        self._bpath = None
        self._bfragment = None
        self._buserinfo = None
        self._bquery_params = None
        self._bconnection = None # from header
        self._bcontent_type = None
        self._bagent = None
        self._baccept = None
        self._baccept_encoding = None
        self._bcookies = None
        self._bcache_control = None
        self._bcontent_length = None
        self._bboundary = None
        # basic data
        self.method = None
        self.raw = None
        self.form = None
        self.json = None
        self.file = None

    def add_burl(self, burl):
        self.__burl = burl
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
        ''' 1. agent阻止指定agent访问
            2. cache-control缓存控制
            3. host跨域
        '''
        bname = bname.strip()
        self.__bheaders[bname] = bvalue
        l_bname = bname.lower()

        if l_bname == b"host":
            self._bhost = bvalue
        elif l_bname == b"connection":
            pass
        elif l_bname == b"content-type":
            self._bcontent_type = bvalue
            if bvalue.find(b"form-data") > -1:
                _, bb = bvalue.split(b";")
                bboundary = bb.split(b"=")[1].strip()
                bboundary = b"--" + bboundary
                self._bboundary = bboundary
        elif l_bname == b"content-length":
            self._bcontent_length = bvalue
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

    def add_bbody(self, bbody):
        ''' 
            1. x-www-form-urlencoded -> self.form + self.raw
            2. form-data             -> self.form
            3. raw(text)             -> self.raw
            4. raw(json)             -> self.raw + self.json
            5. binary(text)          -> self.file
            6. binary(octect-stream) -> self.file
            7. binary(o-MIME)        -> self.file
        '''
        self.__bbody = bbody
        
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
                        field_keys = bkey_pattern.findall(bfdes)
                        if field_keys: # field
                            form[field_keys[0].decode()] = bf.decode()
                            continue
                        file_keys = bfile_pattern.findall(bfdes)
                        if file_keys: # file (binary value)
                            file_key = file_keys[0]
                            if file_key:
                                form[file_key.decode()] = bf
                                continue
                            else:
                                file_keys = bfile_pattern2.findall(bfdes)
                                form[file_keys[0].decode()] = bf
            self.form = form
        elif bcontent_type.find(b"text/plain") > -1:
            self.raw = bbody.decode()
        elif bcontent_type.find(b"json") > -1:
            body = bbody.decode()
            self.json = json.loads(body)
        elif bcontent_type.find(b"octet-stream") > -1:
            self.file = bbody
        else: # other MIME(no name tag.)
            self.file = bbody
        
    def set_method(self, method):
        self.method = method

    def get_method(self):
        return self.method

    def get_url(self):
        burl = self.__burl
        if burl.endswith(b"/"):
            burl = burl[:-1]
        return burl.decode()

    def get_headers(self):
        headers = {}
        bheaders = self.__bheaders
        for bname, bvalue in bheaders.items():
            name = bname.decode()
            value = bvalue.decode()
            headers[name] = value
        return headers

    @property
    def body(self):
        bbody = self.__bbody
        return bbody.decode()

gmt_format = "%a, %d %b %Y %H:%M:%S GMT"
class Response:
    __slots__ = (
        "__protocol",
        "version",
        "code",
        "msg",
        "headers",
    )

    def __init__(self, protocol, version= "1.1"):
        self.__protocol = protocol
        self.version = version
        self.reset()

    def reset(self):
        self.code = 200
        self.msg = "OK"
        self.headers = {
                "Content-Type": "text/plain;charset=utf-8",
                "Connection": "close"} # default close

    def set_keep_alive(self, keep_alive_tm=60):
        if keep_alive_tm:
            self.headers["Connection"] = "keep-alive"
            self.headers["Keep-Alive"] = keep_alive_tm
        else:
            self.headers["Connection"] = "close"
            self.headers["Keep-Alive"] = None

    def update_version(self, version):
        if version > self.version:
            self.version = version

    def update_headers(self, headers={}):
        self.headers.update(headers)

    def encode_headers(self):
        headers = ""
        hs = self.headers
        for h, v in hs.items():
            if v:
                headers += f"{h}: {v}\r\n"
        title = f"HTTP/{self.version} {self.code} {self.msg}\r\n"
        return title.encode() + headers.encode()

    def error(self, unlight_exc):
        self.code = unlight_exc.err_code
        self.msg = unlight_exc.err_msg
        enc_headers = self.encode_headers()
        self.__protocol.fatal(enc_headers + b"\r\n" + b"")
        self.reset() # reset

    def text(self, data):
        enc_data = data.encode()
        self.headers["Content-Type"] = "text/plain"
        self.headers["Content-Length"] = len(enc_data)
        self.__protocol.write(self.encode_headers() + b"\r\n" + enc_data)

    def html(self, path):
        data = None
        with open(path) as f:
            data = f.read()
        enc_data = data.encode()
        self.headers["Content-Type"] = "text/html"
        self.headers["Content-Length"] = len(enc_data)
        self.__protocol.write(self.encode_headers() + b"\r\n" + enc_data)

    def json(self, data):
        enc_data = json.dumps(data)
        self.headers["Content-Type"] = "application/json"
        self.headers["Content-Length"] = len(enc_data)
        self.__protocol.write(self.encode_headers() + b"\r\n" + enc_data)

    def file(self, path):
        data = None
        with open(path) as f:
            data = f.read()
        enc_data = data.encode()
        self.headers["Content-Type"] = "application/octet-stream"
        self.headers["Content-Length"] = len(enc_data)
        self.__protocol.write(self.encode_headers() + b"\r\n" + enc_data)
