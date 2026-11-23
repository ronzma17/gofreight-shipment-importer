"""
本地假服务器 —— 开发时用的, 不是 GoFreight 的沙箱。

作用: 在还没有 key、或者不想动真系统的时候, 把整条链路跑通一遍,
确认 csv 读得对、JSON 拼得对、报错处理没问题。

怎么用(开两个命令行窗口):

  窗口 1    python dev/mock_gofreight.py

  窗口 2    set GOFREIGHT_BASE_URL=http://127.0.0.1:8900
            set GOFREIGHT_API_KEY=LOCAL-TEST
            python push.py examples/shipments.csv --go

注意第二个窗口里那两行 set —— 它们只在那个窗口里有效,
关掉就没了, 不会污染你真正的环境变量。
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

KEY = "LOCAL-TEST"
DB = []


class H(BaseHTTPRequestHandler):

    def log_message(self, *a):
        pass

    def say(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def ok_key(self):
        return self.headers.get("X-GATEWAY-TOKEN") == KEY

    def do_GET(self):
        u = urlparse(self.path)
        if not self.ok_key():
            print(f"  GET  {u.path}  -> 401 key 不对")
            return self.say(401, {"error": "bad key"})

        if u.path == "/api/v1/shipments/master-bills":
            mbl = (parse_qs(u.query).get("ocean_shipment.mbl_no") or [""])[0]
            hit = [r for r in DB if r["mbl_no"] == mbl]
            print(f"  GET  查 {mbl}  -> {len(hit)} 票")
            return self.say(200, {"results": hit})

        if u.path == "/api/v1/shipments/ocean-import/mbl/custom-field":
            return self.say(200, {"results": [
                {"name": "cf_demo", "label": "演示字段", "type": "text"}]})

        self.say(404, {"error": "no such path"})

    def do_POST(self):
        u = urlparse(self.path)
        if not self.ok_key():
            print(f"  POST {u.path}  -> 401 key 不对")
            return self.say(401, {"error": "bad key"})

        n = int(self.headers.get("Content-Length") or 0)
        d = json.loads(self.rfile.read(n))

        if u.path == "/api/v1/shipments/ocean-import/mbl":
            # 真接口收的是 {"data": [...]}, 这里照抄, 不然测了也白测
            items = d.get("data")
            if not isinstance(items, list) or not items:
                print("  POST 建单 -> 400 data 不是数组")
                return self.say(400, {"error": "data must be a non-empty array"})

            out = []
            for m in items:
                # 规范里主单必填就这三个
                for f in ("mbl_no", "office_ref", "estimated_arrival_date"):
                    if not m.get(f):
                        print(f"  POST 建单 -> 400 缺 {f}")
                        return self.say(400, {"error": f"missing {f}"})
                # 每个柜必填 container_no + container_size_ref
                for c in m.get("container_list") or []:
                    for f in ("container_no", "container_size_ref"):
                        if not c.get(f):
                            print(f"  POST 建单 -> 400 柜子缺 {f}")
                            return self.say(400,
                                            {"error": f"container missing {f}"})
                m["ref"] = f"REF{len(DB)+1:05d}"
                DB.append(m)
                n = len(m.get("container_list") or [])
                print(f"  POST 建单 {m['mbl_no']} ({n} 柜) -> 201 {m['ref']}")
                out.append({"ref": m["ref"], "mbl_no": m["mbl_no"]})

            return self.say(201, {"data": out[0] if len(out) == 1 else out})

        self.say(404, {"error": "no such path"})


print("假 GoFreight 跑在 http://127.0.0.1:8900")
print(f"key = {KEY}")
print("按 Ctrl+C 停止\n")
HTTPServer(("127.0.0.1", 8900), H).serve_forever()
