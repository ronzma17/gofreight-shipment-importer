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
"""

import json
import sys

from gofreight import GoFreight, ApiError


def show(data, keys):
    """只打印关心的几列, 原样 dump 太长没法看"""
    rows = (data or {}).get("data") or (data or {}).get("results") or []
    if not rows:
        print("(空)")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:600])
        return
    for r in rows:
        print("  " + "  ".join(f"{k}={r.get(k, '')}" for k in keys))
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

    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main()
    except ApiError as e:
        print(f"读不到: {e}")
