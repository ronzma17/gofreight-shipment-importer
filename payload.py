"""
把一行 CSV 翻译成 API 要的 JSON。

字段名全部照 GoFreight 的 OpenAPI 规范(bundle-prod.yaml)核对过, 不是猜的。


=====================================================================
建单的真实规则(这些是从规范里挖出来的, 文档正文没写全)
=====================================================================

必填只有三个:
    mbl_no                    主提单号
    office_ref                你们公司在 GoFreight 的办公室编号(纯数字)
    estimated_arrival_date    ETA, 必须 ISO 8601 格式

港口:
    port_of_loading_ref / port_of_discharge_ref
    字段名带 _ref, 但规范里写的是 "POL in UN/LOCODE" ——
    填 CNSHA / USLAX 这种 5 位码, 不是地名, 也不是什么内部 id。
    承运人邮件标题里就带着: ...-CNSHA-USLAX-Notice of Arrival

柜子 container_list, 每个柜必填两项:
    container_no              柜号
    container_size_ref        柜型, 必须是系统里已存在的代码
                              不确定填什么就先跑 lookup.py 把可选值列出来
    其余可选: seal_no / package(件数) / weight / measurement

!! 多柜票的件数重量材积怎么填 —— 这条跟直觉完全相反 !!

    【整票的合计】只填进【第一个柜】, 后面的柜这三项留空。

    不是每个柜填自己的, 也不是去填那个 Total 栏 ——
    那两种填法在界面上看着对, 但【打印出来的单子是错的】。
    这是 GoFreight 自己的毛病, 只能顺着它来。

    所以 csv 里 package / weight / measurement 填【整票合计】就行。
    要是沿用老报告那种按柜分开的写法(520,520), 脚本会自动加起来,
    不用你手工算。

分单 hbl_list, 只有 hbl_no 必填。
    注意: 收发货人在【分单】上, 不在主单上 ——
    shipper_ref / consignee_ref / notify_ref
    填的是对方的 Trade Partner ref, 不是公司名。
=====================================================================
"""

import os
import re

# UN/LOCODE: 2 位国家码 + 3 位地点码
LOCODE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}$")


def split(v):
    """多柜的票柜号是逗号连在一格里的, 拆成列表。"""
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def num(v, kind=float):
    """'12,953.000' -> 12953.0; 空的返回 None。

       csv 里的数字常带千分位逗号, 直接 float() 会炸, 先去掉。
    """
    s = str(v or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return kind(float(s))
    except ValueError:
        return None


def locode(value, field):
    """港口代码在本地先拦一道。

       与其发出去被打回来(浪费一次调用, 还要看一行看不懂的报错),
       不如这里就拦住, 报错能说人话。
    """
    v = (value or "").strip().upper()
    if not v:
        raise ValueError(f"{field} 是空的")
    if not LOCODE.match(v):
        raise ValueError(
            f"{field} = {value!r} 不是 UN/LOCODE。要填 CNSHA 这种 5 位码, "
            f"不是地名。承运人邮件标题里就有(...-CNSHA-USLAX-...)")
    return v


def iso_date(v):
    """ETA 转成 ISO 8601。

       规范要求 date-time 格式。csv 里一般是 2026-12-05 这种,
       补上时间部分就行。
    """
    s = str(v or "").strip()
    if not s:
        raise ValueError("estimated_arrival_date(eta) 是必填的, 不能空")
    s = s.replace("/", "-")
    if len(s) == 10:                       # 2026-12-05
        return s + "T00:00:00Z"
    return s


def totals(row):
    """整票的件数/重量/材积, 填进第一个柜。

       csv 里写成 '520,520' 这种按柜分开的也认 —— 自动加起来,
       省得你为了迁就 GoFreight 的毛病还要手工算一遍合计。
    """
    out = {}
    for csv_name, api_name, kind in (("package", "package", int),
                                     ("weight", "weight", float),
                                     ("measurement", "measurement", float)):
        parts = [num(x, kind) for x in split(row.get(csv_name))]
        parts = [x for x in parts if x is not None]
        if parts:
            v = sum(parts)
            out[api_name] = int(v) if kind is int else round(v, 3)
    return out


def build(row):
    """CSV 的一行 -> 一票的 JSON(还没套最外层的 data 数组)"""

    office = os.environ.get("GOFREIGHT_OFFICE_REF")
    if not office:
        raise SystemExit(
            "没有 GOFREIGHT_OFFICE_REF。\n\n"
            "这是你们公司在 GoFreight 的办公室编号(纯数字), 必填。\n"
            "跑 lookup.py 可以把账号下的办公室列出来, 从里面挑。\n\n"
            '  [Environment]::SetEnvironmentVariable('
            '"GOFREIGHT_OFFICE_REF","那个数字","User")')

    # ---- 柜子 ----
    nos    = split(row.get("container_no"))
    seals  = split(row.get("seal_no"))
    sizes  = split(row.get("container_size_ref"))

    containers = []
    for i, no in enumerate(nos):
        c = {
            "container_no": no,
            # 柜型取不到就用第一个 —— 多柜票经常只写一次柜型,
            # 意思是每个柜都一样
            "container_size_ref": sizes[i] if i < len(sizes) else (
                sizes[0] if sizes else ""),
        }
        if i < len(seals):
            c["seal_no"] = seals[i]
        containers.append(c)

    # 件数/重量/材积: 整票的合计, 全部填进【第一个柜】, 其余柜留空。
    # 原因见文件开头 —— 按柜分开填或者填 Total 栏, 打出来的单子都是错的。
    if containers:
        containers[0].update(totals(row))

    # ---- 主单 ----
    mbl = {
        "office_ref": office,
        "mbl_no": row["mbl_no"],
        "estimated_arrival_date": iso_date(row.get("eta")),
    }
    if row.get("pol"):
        mbl["port_of_loading_ref"] = locode(row["pol"], "pol")
    if row.get("pod"):
        mbl["port_of_discharge_ref"] = locode(row["pod"], "pod")
    if containers:
        mbl["container_list"] = containers
    for name in ("vessel_name", "voyage"):
        if row.get(name):
            mbl[name] = row[name].strip()

    # 单位。规范里 weight_unit 只收 KG/LB, measurement_unit 只收 CBM/CFT。
    # 不填的话用的是账号默认值 —— 万一默认是 LB, 12528 就会被当成磅,
    # 差了一倍多还不报错, 所以这里明确写死。
    mbl["weight_unit"] = (row.get("weight_unit") or "KG").strip().upper()
    mbl["measurement_unit"] = (row.get("measurement_unit") or "CBM").strip().upper()

    # 件数的单位(CARTON(S) 之类)是个 ref, 要从 Get Package Units 查。
    # 跑 python lookup.py packages 看可选值。没设就不填, 让系统用默认的。
    pkg_unit = row.get("package_unit_ref") or os.environ.get(
        "GOFREIGHT_PACKAGE_UNIT_REF")
    if pkg_unit:
        mbl["package_unit_ref"] = pkg_unit.strip()

    # ---- 分单 ----
    # 收发货人在分单上, 不在主单上。
    # hbl_no 可以是逗号分隔的多个 —— 分单票(同一个 MBL 拆成几个 HBL)
    # 在 GoFreight 这边就是一个主单挂多个分单。
    hbls = split(row.get("hbl_no"))
    if hbls:
        shared = {}
        for name in ("shipper_ref", "consignee_ref", "notify_ref",
                     "description", "mark"):
            if row.get(name):
                shared[name] = row[name].strip()
        # 多个分单时这几项是共用的 —— 分单各自不同的那部分
        # 现在填不了(报告里没按分单拆开), 建完人工补
        mbl["hbl_list"] = [dict(shared, hbl_no=h) for h in hbls]

    return mbl


if __name__ == "__main__":
    import csv
    import json
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "examples/shipments.csv"
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            # 真发的时候外面还要套一层 {"data": [...]}
            print(json.dumps({"data": [build(row)]}, ensure_ascii=False, indent=2))
            break
