from os import environ, path as ospath

from .exception import UnlightException
from .lightlog import lightlog
unlight_logger = lightlog.get_logger("unlight2")


class HttpRouter:
    ''' simple router for GET/POST methods and static access
        * happy to upgrade it for more powerful! *
    '''

    instance = None
    ''' aggregation and linked for all route path. '''

    def __init__(self):
        raise NotImplementedError('''HttpRouter can not be initialized.
            please use 
                `get_router()` to use router and
                `router.get("/path/to/handler")`
                `router.post("/path/to/handler")`
                `router.static("/path/to/relat_resource", "/path/to/dest_resource")`
                ...
            instead of initialization. For exmaple:
                router = HttpRouter.get_router()
                
                router.get("/hello.html")
                def hello(request, response):
                    response.text("hello, nice to meet you ~")
            ''')

    @classmethod
    def get_router(cls):
        instance = cls.instance
        if not instance:
            instance = object.__new__(cls)

        root_dir = environ.get("PWD")
        instance.root_dir = root_dir
        # initialize route table(template)
        instance.map = {"GET": {}, "POST": {}, "STATIC": {}}
        cls.instance = instance
        return instance

    def get(self, path):
        ''' register `GET METHOD`:
                router.get("/path/to") '''
        def wrapper(func):
            self.map["GET"][path] = func
            return func
        return wrapper

    def post(self, path):
        ''' register `POST METHOD`:
                router.post("/path/to") '''
        def wrapper(func):
            self.map["POST"][path] = func
            return func
        return wrapper

    def set_static_dir(self, path, dest_path):
        ''' build static access dir map '''
        fp = ospath.join(self.root_dir, dest_path)
        if ospath.exists(fp) and ospath.isdir(fp):
            if path[0] != "/": # startswith "/"
                path = f"/{path}"
            self.map["STATIC"][path] = ospath.join(self.root_dir, dest_path)
        else:
            raise NameError(f"static dir is not exists or not dir type: {fp}")

    async def handle_request(self, request, response):
        ''' no strict '''
        method = request.get_method()
        path = request.get_url()
        if not (method and path):
            response.error(UnlightException(404))
            return

        handle = None
        if method.lower() == "get":
            handle = self.map["GET"].get(path)
            if not handle: # maybe static path
                iter_map = self.map["STATIC"]
                for path_key, path_dest in iter_map.items():
                    if path.startswith(path_key):
                        real_path = path_dest
                        last_path = path[len(path_key):]

                        if last_path[0] == "/":
                            last_path = last_path[1:]
                        real_path = ospath.join(real_path, last_path)
                        if ospath.exists(real_path):
                            if last_path.endswith("html"):
                                response.html(real_path)
                            else:
                                response.file(real_path)
                            return
                response.error(UnlightException(404))
                return
        elif method.lower() == "post":
            handle = self.map["POST"].get(path)
            if not handle:
                response.error(UnlightException(404))
                return

        try:
            await handle(request, response)
        except UnlightException as e:
            unlight_logger.error("Unlight2 exception request: ------ ", e)
            response.error(e)
        except Exception as e:
            unlight_logger.error("Unlight2 error request: ------ ", e)
            response.error(UnlightException(500))
