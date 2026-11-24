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


def rows_of(data):
    """把列表接口的返回拆成一个 list。

       GoFreight 的列表都长这样: {"meta": {...}, "data": [ ... ]}。

       2026-11-24 血的教训: find_mbl 里我写的是 .get("results") ——
       那个键【根本不存在】, 所以它永远返回空。后果不是查不到东西
       这么简单: find_mbl 是建单之前"先查后建"那道防重复的闸,
       它永远返回空 = 这道闸从来没关上过。要不是先推一票发现查不到,
       44 票重复单就建出去了。
       以后再写列表接口, 一律走这个函数, 不要各写各的。
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("data", "results"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    return []


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
        rows = rows_of(data)

        # 这个接口是【包含】匹配, 不是精确匹配:
        #   2026-11-24 实测 mbl_no="1" 返回 100 条(翻页上限),
        #   因为所有含 "1" 的单号都被算进来了。
        # 直接拿它当"已存在"用会误判: 查 CMDU123 时 CMDU1234 也会命中,
        # 于是该建的票被当成重复跳过, 整票漏掉还不报错。
        # 所以这里再自己卡一道精确相等。
        want = (mbl_no or "").strip().upper()
        exact = [r for r in rows
                 if isinstance(r, dict)
                 and str((r.get("ocean_shipment") or {}).get("mbl_no")
                         or r.get("mbl_no") or "").strip().upper() == want]
        return exact

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

        # 发的是数组, 收的也是数组: {"data": [ {...} ]}。
        # 我们一次只发一票, 所以这里把它拆开, 直接返回那一票的 dict。
        # 2026-11-24 踩过: 原来直接把 list 返回去, 调用方 .get("ref") 直接
        # AttributeError —— 而且单子【已经建好了】, 崩在记日志之前,
        # 结果系统里有、本地日志没有。所以这里必须拆干净。
        out = data.get("data") if isinstance(data, dict) else data
        if out is None:                      # 没有 data 这层, 那 data 本身就是
            out = data
        if isinstance(out, list):
            return out[0] if out else {}
        return out if isinstance(out, dict) else {}

    def get_mbl(self, ref):
        """按 ref(FOI-0000430 这种)查单票的【完整】内容。

           find_mbl 用的列表接口只给摘要, 看不到柜子和分单。
           要核对件数/重量/材积有没有进对地方, 必须查这个。
        """
        data = self._call("GET", f"/api/v1/shipments/ocean-import/mbl/{ref}")
        out = data.get("data") if isinstance(data, dict) else data
        if isinstance(out, list):
            return out[0] if out else {}
        return out if isinstance(out, dict) else {}

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

    def trade_partner(self, ref):
        """按 TP 编号查一个客户/代理。查不到就返回 {}。

           TP 编号是【每个租户自己的】—— 沙箱里的 TP-000020 和真系统里的
           TP-000020 根本不是同一家公司, 甚至可能一个有一个没有。
           所以建单之前必须验一次, 不能假设编号通用。
        """
        try:
            data = self._call("GET", f"/api/v1/trade-partners/{ref}")
        except ApiError as e:
            if e.status == 404:
                return {}
            raise
        out = data.get("data") if isinstance(data, dict) else data
        if isinstance(out, list):
            return out[0] if out else {}
        return out if isinstance(out, dict) else {}

    def custom_fields(self):
        """看看这个账号有哪些自定义字段。建单前先跑一次, 心里有数。"""
        return self._call(
            "GET", "/api/v1/shipments/ocean-import/mbl/custom-field")
