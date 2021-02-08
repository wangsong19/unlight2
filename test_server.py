from unlight2 import server as u2

# 创建服务
server = u2.Server(("127.0.0.1", 9919))

# 添加服务路由处理
@server.router.get("/hello")
async def hello(request, response):
    response.text("hello world!")

@server.router.post("/modify_raw")
async def modify_raw(request, response):
    way = "by_raw_old"
    way = request.raw
    response.text(f"modify ok, new way: {way}")

@server.router.post("/modify_json")
async def modify_json(request, response):
    data = {"way": "by_json_old"}
    data["way"] = request.json.get("way")
    response.text(f"modify ok, new data: {data}")

# 设置静态访问目录为当前目录
server.router.set_static_dir("static", ".")
# 通过表单上传指定文件(虽然使用get也能正常解析路径,但正常使用post请求做方法绑定)
@server.router.post("/upload_file")
async def upload_file(request, response):
    form = request.form
    for key, value in form.items():
        if type(value) is bytes:
            with open(key, "wb") as f:
                f.write(value)
        else:
            print("--- other key: ", key, value)
    response.text("ok!")

server.run_multi_process(n=0)
