"""
跟 GoFreight API 打交道的代码全在这里。

别的文件不直接发网络请求, 都通过这里走。
这样认证、报错处理只写一遍, 不会这里写了那里忘。
"""

import os

try:
    import requests
except ImportError:
    raise SystemExit("缺 requests, 先跑:  pip install requests")


# 接口地址。GOFREIGHT_BASE_URL 这个环境变量是留给本地测试用的,
# 平时不用管它, 默认就是 GoFreight 的正式地址。
BASE = os.environ.get("GOFREIGHT_BASE_URL", "https://api.core.gofreight.co")


class ApiError(Exception):
    """接口返回了错误。把状态码和原文都带上, 不然出事了没法查。"""

    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")


class GoFreight:

    def __init__(self):
        # key 从环境变量读, 不从文件读, 更不写在代码里。
        # 用 .get() 而不是 os.environ[...] —— 取不到时能给一句人话,
        # 而不是甩一串看不懂的 KeyError。
        key = os.environ.get("GOFREIGHT_API_KEY")
        if not key:
            raise SystemExit(
                "没有找到 GOFREIGHT_API_KEY 这个环境变量。\n\n"
                "PowerShell 里设一次(以后都不用再设):\n"
                '  [Environment]::SetEnvironmentVariable('
                '"GOFREIGHT_API_KEY","你的key","User")\n\n'
                "设完【重新开一个命令行窗口】再跑 —— "
                "原来那个窗口读不到新设的变量。"
            )

        # 用 Session 而不是每次 requests.post():
        #   1. 请求头只写一次, 不会漏
        #   2. 连接能复用, 几十次请求不用重复握手
        self.s = requests.Session()
        self.s.headers.update({
            "X-GATEWAY-TOKEN": key,        # <- 认证就靠这一行
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    # ------------------------------------------------------------------

    def _call(self, method, path, **kw):
        """所有请求的统一出口, 顺便统一处理报错。"""
        r = self.s.request(method, BASE + path, timeout=30, **kw)

        # 这里不用 raise_for_status(), 因为它的报错信息太简略,
        # 看不到服务器到底说了什么。自己抛能把原文带出来, 排查快很多。
        if r.status_code >= 400:
            raise ApiError(r.status_code, r.text[:500])

        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    # ------------------------------------------------------------------

    def find_mbl(self, mbl_no):
        """按主提单号查, 返回找到的列表(没有就是空的)。

           建单之前一定先查一次, 不然脚本跑第二遍就会建出一堆重复的。
           而且你一定会跑第二遍 —— 第一遍总有几票会失败。
        """
        data = self._call("GET", "/api/v1/shipments/master-bills", params={
            "transportation_mode": "OI",          # OI = Ocean Import
            "ocean_shipment.mbl_no": mbl_no,
        })
        return (data or {}).get("results") or []

    def create_ocean_import_mbl(self, mbl):
        """建一票海运进口主单(连柜子和分单一起)。

           请求体是 {"data": [...]} —— 这个接口本来就收数组,
           一次能建好几票。这里一次只放一票, 是故意的:
           一票一个请求, 哪票失败一目了然, 不会整批一起回滚。

           以后如果调用次数要省(他们按调用量计费), 可以改成
           一次塞十几票进去, 代价是出错时不好定位。
        """
        data = self._call("POST", "/api/v1/shipments/ocean-import/mbl",
                          json={"data": [mbl]})
        return (data or {}).get("data") or data

    def offices(self):
        """列出账号下的办公室, office_ref 从这里来(只读)。"""
        return self._call("GET", "/api/v1/offices")

    def container_sizes(self):
        """列出系统认的柜型代码, container_size_ref 从这里来(只读)。"""
        return self._call("GET", "/api/v1/shipments/container-sizes")

    def package_units(self):
        """列出件数单位(CARTON(S) 之类), package_unit_ref 从这里来(只读)。"""
        return self._call("GET", "/api/v1/package-units")

    def trade_partners(self, **params):
        """查 trade partner, shipper_ref 这些从这里来(只读)。"""
        return self._call("GET", "/api/v1/trade-partners", params=params)

    def custom_fields(self):
        """看看这个账号有哪些自定义字段。建单前先跑一次, 心里有数。"""
        return self._call(
            "GET", "/api/v1/shipments/ocean-import/mbl/custom-field")
