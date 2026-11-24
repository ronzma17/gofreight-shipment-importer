"""
把提单打印工具出的 _报告.xlsx 转成 push.py 能吃的 csv。

两边的数据其实是同一批, 只是列名和格式不一样, 这个脚本负责翻译。

用法:
    python from_report.py _报告.xlsx --eta 2026-12-05
    python from_report.py _报告.xlsx --eta 2026-12-05 -o 本批.csv


为什么 ETA 要手动给
-------------------
舱单(BKG LIST)里没有 ETA 这一列, 所以报告里那一列一直是空的。
但同一条船上所有票的 ETA 本来就一样, 从到港通知上抄一个数进来就行,
比让脚本去猜靠谱。


分单怎么处理
------------
同一个 MBL 下的多个 HBL(报告里是连着的两行, 第二行"第几张纸"是空的),
在 GoFreight 那边是【一个主单挂多个分单】, 所以这里会合并成一行,
hbl_no 用逗号隔开。合并了会在屏幕上告诉你。
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import collections

try:
    import openpyxl
except ImportError:
    raise SystemExit("缺 openpyxl, 先跑:  pip install openpyxl")

HERE = Path(__file__).parent

# push.py / payload.py 认的列
OUT_COLS = ["mbl_no", "hbl_no", "pol", "pod", "eta", "vessel_name", "voyage",
            "container_no", "seal_no", "container_size_ref",
            "package", "weight", "measurement",
            "shipper_ref", "consignee_ref", "notify_ref",
            "description", "mark"]


def load_locodes():
    """港口名 -> UN/LOCODE 的对照表。

       存成 csv 而不是写死在代码里, 是因为你迟早会遇到新港口 ——
       到时候加一行就行, 不用改代码。
       拿到 key 之后也可以用 GET /api/v1/locations 核对这张表。
    """
    table = {}
    p = HERE / "locodes.csv"
    if not p.exists():
        return table
    with open(p, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            name = (r.get("港口名") or "").strip().upper()
            code = (r.get("locode") or "").strip().upper()
            if name and code:
                table[name] = code
    return table


def to_locode(name, table, seen_bad):
    """把 'LOS ANGELES' 变成 'USLAX'。

       认不出来就留空并记一笔 —— 不瞎猜。
       猜错一个港口, 整票的航线就错了, 比空着严重得多。
    """
    raw = str(name or "").strip().upper()
    if not raw:
        return ""
    if raw in table:
        return table[raw]
    # 舱单里常写成 'LOS ANGELES, CALIFORNIA', 逗号前那截再试一次
    head = raw.split(",")[0].strip()
    if head in table:
        return table[head]
    # 本来就是 5 位代码的话直接用
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", raw):
        return raw
    seen_bad.add(raw)
    return ""


def split_vessel(vessel, voyage):
    """船名和航次填到一起时拆开。

       GoFreight 那边这是两个字段。但在命令行上很容易一口气敲成
         "CMA CGM WHITE SHARK EXX0K0E"
       然后航次那栏留空, 结果单子上航次是空的。

       所以航次为空、而船名最后一段【带数字】时, 就把它当航次切出来。
       "CMA CGM WHITE SHARK" 最后一段是 SHARK, 纯字母, 不会被误切。
    """
    vessel = (vessel or "").strip()
    voyage = (voyage or "").strip()
    if voyage or " " not in vessel:
        return vessel, voyage

    head, _, last = vessel.rpartition(" ")
    if re.fullmatch(r"[A-Z0-9]{4,10}", last) and any(c.isdigit() for c in last):
        return head, last
    return vessel, voyage


def anonymize(rows):
    """把能认出客户的东西换掉, 只保留数据的【形状】。

       为什么要有这个: GoFreight 的沙箱是【多家客户共用】的环境,
       他们自己也写了别往里放敏感信息。但纯用假数据又测不出你真实数据里
       那些麻烦情况 —— 多柜、分单、45HC、走 NY 的那几票。

       所以这里只换掉身份, 保留形状:
         提单号      -> DEMO 开头的流水号(分单的 A/B 后缀保留)
         货描/唛头   -> 固定占位
         柜号/封条   -> 换成假的, 但【柜子个数不变】
       港口/柜型/件数/重量/材积【原样保留】——
       这些不指向具体客户, 而且正是最该测的部分。
    """
    for n, r in enumerate(rows, 1):
        r["mbl_no"] = f"DEMO{n:07d}"
        # 分单那票有好几个 hbl, 个数要保住, 不然测不到多分单的情况
        k = len([h for h in r["hbl_no"].split(",") if h.strip()])
        r["hbl_no"] = ",".join(f"DEMOH{n:05d}{chr(65+i)}" for i in range(k)) if k else ""
        ctn = [c for c in r["container_no"].split(",") if c.strip()]
        r["container_no"] = ",".join(f"DEMU{n:04d}{i:03d}" for i in range(len(ctn)))
        r["seal_no"] = ",".join(f"S{n:04d}{i:02d}" for i in range(len(ctn)))
        r["description"] = "GENERAL CARGO"
        r["mark"] = "N/M"
        r["shipper_ref"] = r["consignee_ref"] = r["notify_ref"] = ""
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report", help="_报告.xlsx")
    ap.add_argument("--eta", required=True,
                    help="这条船的 ETA, 比如 2026-12-05(建单必填)")
    ap.add_argument("--vessel", default="",
                    help="船名(可选; 默认用报告里从 B/L 扫出来的)")
    ap.add_argument("--voyage", default="",
                    help="航次(可选; 我们一般不填)")
    ap.add_argument("-o", "--out", default="shipments.csv")
    ap.add_argument("--anonymize", action="store_true",
                    help="把提单号/货描等换成假的, 只保留结构。"
                         "往共享的沙箱环境推数据时【必须】加这个")
    args = ap.parse_args()

    ws = openpyxl.load_workbook(args.report, data_only=True)["明细"]
    # 报告里真正要人处理的行是【淡紫底色】的。状态列的文字里混着很多
    # 常态提示(比如"没有 Waybill"), 按文字筛会把 62 票全筛出来, 等于没筛。
    LILAC = "EDE7F6"
    hdr = [c.value for c in ws[1]]
    idx = {h: i for i, h in enumerate(hdr) if h}

    need = ["MBL", "HBL", "柜号", "封条", "柜型", "件数", "重量", "材积"]
    missing = [c for c in need if c not in idx]
    if missing:
        raise SystemExit(f"报告里缺这几列, 格式对不上: {missing}")

    def cell(row, name):
        i = idx.get(name)
        if i is None or i >= len(row):
            return ""
        v = row[i]
        return "" if v is None else str(v).strip()

    # 船名/航次从报告里扫出来(prep_print.py 从 B/L 上抠的)。命令行给了就以命令行为准。
    seen_vessel = collections.Counter()
    no_vessel = []

    table = load_locodes()
    bad_ports = set()
    merged = []          # 合并掉的分单, 最后报给人看
    problems = []        # 状态不是"正常"的, 提醒复核

    # 按 MBL 归并 —— 分单是同一个主单下的多个分单
    groups = {}
    flagged = set()      # 底色是淡紫的那些 MBL
    order = []
    for cells in ws.iter_rows(min_row=2):
        row = [c.value for c in cells]
        mbl = cell(row, "MBL")
        if not mbl:
            continue
        fill = cells[idx["MBL"]].fill.fgColor.rgb
        if isinstance(fill, str) and fill[-6:].upper() == LILAC:
            flagged.add(mbl)
        if mbl not in groups:
            groups[mbl] = []
            order.append(mbl)
        groups[mbl].append(row)

    out_rows = []
    for mbl in order:
        rows = groups[mbl]
        first = rows[0]

        hbls = [cell(r, "HBL") for r in rows]
        hbls = [h for h in hbls if h]
        if len(rows) > 1:
            merged.append(f"{mbl}  {len(rows)} 个分单 -> {','.join(hbls)}")

        if mbl in flagged:
            problems.append(f"{mbl}  {cell(first, '状态')[:70]}")

        vessel, voyage = split_vessel(args.vessel or cell(first, "船名"),
                                      args.voyage or cell(first, "航次"))
        if vessel:
            seen_vessel[(vessel, voyage)] += 1
        else:
            no_vessel.append(mbl)

        out_rows.append({
            "mbl_no": mbl,
            "hbl_no": ",".join(hbls),
            "pol": to_locode(cell(first, "起始港"), table, bad_ports),
            "pod": to_locode(cell(first, "目的地"), table, bad_ports),
            "eta": args.eta,
            "vessel_name": vessel,
            "voyage": voyage,
            "container_no": cell(first, "柜号"),
            "seal_no": cell(first, "封条"),
            "container_size_ref": cell(first, "柜型"),
            # 这三项 payload.py 会处理: 多柜时自动加总, 只填进第一个柜
            "package": cell(first, "件数"),
            "weight": cell(first, "重量"),
            "measurement": cell(first, "材积"),
            # trade partner 的 ref 这里填不了 —— 报告里只有公司名。
            # 跑 lookup.py partners 查到 ref 之后手工补, 或者建完在界面上补
            "shipper_ref": "", "consignee_ref": "", "notify_ref": "",
            "description": cell(first, "Description of Goods").replace("\n", " "),
            "mark": cell(first, "Marks and Numbers").replace("\n", " "),
        })

    if args.anonymize:
        out_rows = anonymize(out_rows)

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        w.writerows(out_rows)

    # ---- 报告给人看 ----
    print(f"写出 {len(out_rows)} 票 -> {args.out}")
    if args.anonymize:
        print("  已脱敏: 提单号/柜号/封条/货描都换成假的了, 柜数和港口保持原样")
    else:
        print("  !! 没脱敏 —— 里面是真实客户资料")
        print("     要往【共享的沙箱】推的话, 请加 --anonymize 重跑一次")
    print(f"ETA 统一填 {args.eta}")

    # 船名是自动扫的, 所以必须让人看见扫出来的是什么 —— 不然错了没人知道
    for (vs, vy), n in seen_vessel.most_common():
        src = "命令行给的" if args.vessel else "报告里扫出来的"
        print(f"船名({src}): {vs}" + (f"   航次: {vy}" if vy else "   航次: 空")
              + f"   {n} 票")
        if vy and vy not in (args.voyage, ""):
            if f" {vy}" in (args.vessel or ""):
                print("  (船名后面带着航次, 已经拆开了)")
    if len(seen_vessel) > 1:
        print("  !! 一个报告里出现了多个船名, 正常一批只有一条船, 请先核对")
    if no_vessel:
        print(f"\n!! 这 {len(no_vessel)} 票扫不到船名, 对应的票船名是空的:")
        print("  " + ", ".join(no_vessel[:8]))
        print("  报告是旧版的(没有【船名】列)就用 --vessel \"船名\" 手动给")

    if merged:
        print(f"\n合并了 {len(merged)} 个分单(同 MBL 多 HBL):")
        for m in merged:
            print("  " + m)

    if bad_ports:
        print(f"\n!! 这些港口名查不到 LOCODE, 对应的票港口是空的:")
        for p in sorted(bad_ports):
            print(f"  {p}")
        print("  去 locodes.csv 里加一行就行(港口名,locode)")

    if problems:
        print(f"\n这 {len(problems)} 票在报告里标了淡紫(真问题), 推之前先处理:")
        for p in problems[:10]:
            print("  " + p)
        if len(problems) > 10:
            print(f"  ...还有 {len(problems)-10} 票")

    no_ctn = [r["mbl_no"] for r in out_rows if not r["container_no"]]
    if no_ctn:
        print(f"\n!! 这 {len(no_ctn)} 票没有柜号: {', '.join(no_ctn[:5])}")

    print(f"\n下一步:  python push.py {args.out}       (先看, 不发)")
    print(f"        python push.py {args.out} --go  (真发)")


if __name__ == "__main__":
    main()
