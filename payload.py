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
from datetime import datetime

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


def iso_date_opt(v):
    """跟 iso_date 一样, 但空值返回空串而不是报错。
       ETD 不是必填 —— B/L 上没盖 ON BOARD 戳的时候就该留空。"""
    return iso_date(v) if str(v or "").strip() else ""


def iso_date(v):
    """ETA 转成 API 要的 ISO 8601。

       格式必须是 YYYY-MM-DDTHH:MM:SS, 【结尾不能有 Z】。
       2026-11-24 实测: 发 '2026-12-02T00:00:00Z' 被打回 ——
         HTTP 400 field: data.estimated_arrival_date,
         reason: Invalid data format, should be YYYY-MM-DDTHH:MM:SS
       Z 是 ISO 8601 的 UTC 标记, 大多数 API 收, GoFreight 不收。
       规范 bundle-prod.yaml 里只写了 format: date-time, 没说清,
       所以这条只能靠真发一票才知道。别再把 Z 加回去。

       两种写法都认:
           2026-12-05   年在前(推荐)
           12/05/2026   月/日/年, 到港通知上就是这么印的

       为什么特意管第二种: 你多半会照着到港通知抄, 而那上面写的是
       "POD ETA: 11/02/2026"。原来的代码碰到它会变成
       12-05-2026T00:00:00 —— 不是合法 ISO, 发出去被打回,
       而且报错只说日期不对, 不会告诉你是格式反了。

       认不出来的直接拦住, 不猜。日期猜错了比没填还糟:
       ETA 错一天, 后面的免柜期、提柜安排全跟着错。
    """
    s = str(v or "").strip()
    if not s:
        raise ValueError("eta 是必填的(API 的 estimated_arrival_date), 不能空")

    # 已经是 ISO 日期时间的原样放行。这里要卡死成 2026-12-05 开头 ——
    # 以前只看"有没有 T 或空格"就放行, 结果 'Dec 5 2026' 也混过去了
    if re.match(r"^\d{4}-\d{2}-\d{2}([T ]|$)", s):
        # 长得像不等于是真日期 —— 2026-13-45 也长这样, 还是要验一遍
        try:
            datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"eta = {v!r} 不是有效日期 ({e})")
        if len(s) <= 10:
            return s + "T00:00:00"
        # 带了时间的: 只取【日期 + 时分秒】, 把 'Z'、'+08:00' 这类时区后缀扔掉。
        # GoFreight 明确要 YYYY-MM-DDTHH:MM:SS, 多一个 Z 就 400。
        m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)", s)
        if m:
            hms = m.group(2)
            return f"{m.group(1)}T{hms if len(hms) == 8 else hms + ':00'}"
        return s[:10] + "T00:00:00"

    parts = re.split(r"[/\-.]", s)
    if len(parts) == 3:
        a, b, c = (x.strip() for x in parts)
        if len(a) == 4:                      # 2026-12-05
            y, m, d = a, b, c
        elif len(c) == 4:                    # 12/05/2026  月在前(美式)
            y, m, d = c, a, b
        else:
            raise ValueError(
                f"eta = {v!r} 看不出年份在哪。写成 2026-12-05 或 12/05/2026")
        try:
            dt = datetime(int(y), int(m), int(d))
        except ValueError as e:
            raise ValueError(f"eta = {v!r} 不是有效日期 ({e})")
        return dt.strftime("%Y-%m-%dT00:00:00")

    raise ValueError(
        f"eta = {v!r} 格式认不出来。写成 2026-12-05 或 12/05/2026")


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

    # ---- 每票都要填的几项 ----
    # ETD = B/L 右上角 ON BOARD 戳的日期, prep_print.py 从单子上抠的。
    # 每票可能不一样(同一条船也会差一两天), 所以逐票填, 不是常数。
    etd = iso_date_opt(row.get("etd"))
    if etd:
        mbl["estimated_departure_date"] = etd

    # OB/L Type: 我们一律走 Seaway BL。规范里的取值:
    #   E=Express BL   O=Original BL   S=Seaway BL   I=Electronic BL
    mbl["obl_type"] = (row.get("obl_type")
                       or os.environ.get("GOFREIGHT_OBL_TYPE") or "S").strip()

    # Oversea Agent 和 CY Location 是 Trade Partner 编号(TP-xxxxxx)。
    # 放环境变量里, 不写死 —— 沙箱和真系统的编号是两套, 写死了换账号必错。
    #   CHINA ARTS            -> GOFREIGHT_OVERSEA_AGENT_REF
    #   FENIX MARINE (Y257)   -> GOFREIGHT_CY_LOCATION_REF
    for col, env, key in (
            ("oversea_agent_ref", "GOFREIGHT_OVERSEA_AGENT_REF",
             "oversea_agent_ref"),
            ("cy_location_ref", "GOFREIGHT_CY_LOCATION_REF",
             "cy_location_ref")):
        v = row.get(col) or os.environ.get(env)
        if v and v.strip():
            mbl[key] = v.strip()

    # ---- Ramp(转内陆铁路)专有 ----
    # 船在洛杉矶卸, 柜子上火车去纽约。所以:
    #   Service Term 从 CY 到 RAMP(规范里 RAMP 写作 "RM")
    #   交货地填纽约 —— 卸货港还是洛杉矶, 两者不能混
    ramp = str(row.get("is_ramp") or "").strip().upper() in ("Y", "YES", "1",
                                                            "TRUE", "RAMP")
    if ramp:
        mbl["service_term_to"] = "RM"
    if row.get("place_of_delivery"):
        mbl["place_of_delivery_ref"] = locode(row["place_of_delivery"],
                                              "place_of_delivery")

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
        # Express B/L 一律 Yes
        shared["is_express"] = True

        # Ramp 的票: 分单上勾 Rail, IT No. 填 PORT CLEAR。
        # 这两项规范里【只有分单有】, 主单没有 —— 界面上主单 More 里
        # 那个 IT No. 是把分单的显示上来的。
        if ramp:
            shared["is_rail"] = True
            shared["it_no"] = (row.get("it_no")
                               or os.environ.get("GOFREIGHT_RAMP_IT_NO")
                               or "PORT CLEAR").strip()
            shared["service_term_to"] = "RM"
            if mbl.get("place_of_delivery_ref"):
                shared["place_of_delivery_ref"] = mbl["place_of_delivery_ref"]

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
