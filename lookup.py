"""
把建单要用到的那些 ref 查出来(全是只读, 不会改任何东西)。

建单之前跑一次, 把下面三样搞清楚:
    office_ref           你们公司的办公室编号 -> 设成环境变量
    container_size_ref   系统认的柜型代码, 比如 40HC 到底写成什么
    package_unit_ref     件数单位, 比如 CARTON(S)
    shipper_ref 这些     客户在系统里的 Trade Partner 编号

用法:
    python lookup.py offices
    python lookup.py sizes
    python lookup.py packages
    python lookup.py partners 关键字
    python lookup.py mbl DEMO0000001     按主提单号查一票在不在系统里
    python lookup.py recent              最近建的几票(不管负责人是谁)
    python lookup.py detail FOI-0000430  查一票的【全部】内容(柜子/分单都在)
    python lookup.py uri /api/v1/shipments/containers/100417/
                                         顺着返回里的 uri 再查下去
"""

import json
import sys

from gofreight import GoFreight, ApiError, rows_of


def show(data, keys):
    """打印查到的东西。

       keys 只决定【顺序】, 不决定显示哪些 —— 所有字段都会打出来。

       一开始我是只打 keys 里那几列, 结果办公室那个接口翻车了:
       它没有 name/code, 只有 ref 对得上, 于是打出来就是光秃秃一排
       ref=1 ref=2, 看不出哪个是自己家的, 等于白查。
       这种查参照数据的工具, 宁可信息多也不能少。
    """
    # 传原始返回或者已经拆好的 list 都行 —— 2026-11-24 我就是传了 list
    # 进来然后 AttributeError。工具函数宁可多认一种形状。
    rows = data if isinstance(data, list) else rows_of(data)
    if not rows:
        print("(空)")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:600])
        return

    first = rows[0] if isinstance(rows[0], dict) else {}
    # 关心的列排前面, 其余字段按字母跟在后面, 一个都不漏
    order = [k for k in keys if k in first]
    order += [k for k in sorted(first) if k not in order]

    for r in rows:
        if not isinstance(r, dict):
            print("  " + str(r))
            continue
        parts = []
        for k in order:
            v = r.get(k)
            if v in (None, "", [], {}):
                continue
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)[:40]
            parts.append(f"{k}={v}")
        print("  " + "  ".join(parts))
    print(f"\n共 {len(rows)} 条")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    gf = GoFreight()

    if what == "offices":
        print("账号下的办公室(office_ref 从这里挑):\n")
        show(gf.offices(), ["ref", "name", "code"])

    elif what == "sizes":
        print("系统认的柜型(container_size_ref 填这里的代码):\n")
        show(gf.container_sizes(), ["ref", "name", "code"])

    elif what == "packages":
        print("件数单位(package_unit_ref 填这里的 ref):\n")
        show(gf.package_units(), ["ref", "name", "code"])

    elif what == "partners":
        kw = sys.argv[2] if len(sys.argv) > 2 else ""
        print(f"Trade Partner 搜 {kw!r}:\n")
        show(gf.trade_partners(search=kw) if kw else gf.trade_partners(),
             ["ref", "name"])

    elif what == "mbl":
        no = sys.argv[2] if len(sys.argv) > 2 else ""
        if not no:
            raise SystemExit("要给个主提单号:  python lookup.py mbl DEMO0000001")
        rows = gf.find_mbl(no)
        # 这条是用来判生死的: 网页列表是过滤过的视图, 看不到不代表没建成。
        # API 直接按单号查, 查不到才是真没建成。
        if not rows:
            print(f"{no}  —— 系统里【没有】这票")
        else:
            print(f"{no}  —— 找到 {len(rows)} 条:\n")
            show(rows, ["ref", "mbl_no", "office_ref"])

    elif what == "detail":
        ref = sys.argv[2] if len(sys.argv) > 2 else ""
        if not ref:
            raise SystemExit("要给个 ref:  python lookup.py detail FOI-0000430")
        d = gf.get_mbl(ref)
        if not d:
            print(f"{ref}  —— 查不到")
        else:
            # 柜子和分单单独摊开打, 挤在一行里看不清
            ctn = d.pop("container_list", []) or []
            hbl = d.pop("hbl_list", []) or []
            print("主单:")
            for k in sorted(d):
                v = d[k]
                if v in (None, "", [], {}):
                    continue
                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False)[:90]
                print(f"  {k} = {v}")
            print(f"\n柜子 {len(ctn)} 个:")
            for c in ctn:
                print("  " + json.dumps(c, ensure_ascii=False))
            print(f"\n分单 {len(hbl)} 个:")
            for h in hbl:
                print("  " + json.dumps(h, ensure_ascii=False)[:300])

    elif what == "uri":
        # GoFreight 的返回里到处是 "uri": "/api/v1/..." 这种链接 ——
        # 嵌套的东西(柜子、分单)只给链接, 不展开。
        # 这条命令就是顺着链接再查一层, 不用为每种资源单独写个函数。
        u = sys.argv[2] if len(sys.argv) > 2 else ""
        if not u.startswith("/api/"):
            raise SystemExit(
                "要给个 /api/... 开头的链接, 从别的查询结果里复制:\n"
                "  python lookup.py uri /api/v1/shipments/containers/100417/")
        d = gf._call("GET", u)
        body = d.get("data") if isinstance(d, dict) and "data" in d else d
        if isinstance(body, list):
            for one in body:
                print(json.dumps(one, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(body, ensure_ascii=False, indent=2))

    elif what == "recent":
        # 排序参数是 sort.by / sort.direction, 不是 ordering ——
        # 这个接口是 strict mode, 给了它不认识的参数直接 400
        data = gf._call("GET", "/api/v1/shipments/master-bills",
                        params={"transportation_mode": "OI",
                                "sort.by": "created_at",
                                "sort.direction": "desc",
                                "limit": "20"})
        rows = rows_of(data)
        print(f"最近 {len(rows)} 票(不分负责人):\n")
        show(rows, ["ref", "mbl_no", "office_ref"])

    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main()
    except ApiError as e:
        print(f"读不到: {e}")
