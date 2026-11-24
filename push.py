"""
主程序: 读 CSV, 一票一票建进 GoFreight。

默认【只打印不发送】。要真发必须显式加 --go。
写这类批量写入的脚本我一定留这个开关 —— 宁可多敲四个字母,
也不要手一抖把几十票垃圾数据灌进系统, 删起来比建起来难受得多。

用法:
    python push.py examples/shipments.csv            只看 JSON, 不发
    python push.py examples/shipments.csv --go -n 1  真发, 但只发第一票
    python push.py examples/shipments.csv --go       真发, 全部
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from gofreight import GoFreight, ApiError
from payload import build


def read_rows(path):
    # utf-8-sig: Excel 存出来的 csv 开头有个看不见的 BOM,
    # 用普通 utf-8 读的话第一个列名会变成 '﻿mbl_no', 然后到处取不到值。
    # 这个坑很隐蔽, 直接用 utf-8-sig 一劳永逸。
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def log_result(mbl, hbl, ref, note):
    """把结果记到本地 csv。

       这个文件很重要: 下次跑能知道哪些推过了;
       真建错了, 也得靠这里的 ref 才找得回去删。
    """
    p = Path("push_log.csv")
    new = not p.exists()
    with open(p, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["时间", "MBL", "HBL", "ref", "结果"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    mbl, hbl, ref, note])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_file", help="要推送的 csv")
    ap.add_argument("--go", action="store_true",
                    help="真的发出去(不加就只打印)")
    ap.add_argument("-n", "--limit", type=int, default=0,
                    help="只处理前 N 票(0 = 全部)。第一次跑务必先 -n 1")
    ap.add_argument("--only", default="",
                    help="只处理这个 MBL(逗号隔开可以给几个)")
    args = ap.parse_args()

    rows = read_rows(args.csv_file)
    total = len(rows)
    print(f"读到 {total} 票")

    # --only 挑票: 补过单之后只想重推那几票的时候用
    if args.only:
        want = {x.strip().upper() for x in args.only.split(",") if x.strip()}
        rows = [r for r in rows
                if (r.get("mbl_no") or "").strip().upper() in want]
        got = {(r.get("mbl_no") or "").strip().upper() for r in rows}
        for m in sorted(want - got):
            print(f"  !! csv 里找不到 {m}")
        if not rows:
            raise SystemExit("--only 一票都没匹配上, 什么也没做")
        print(f"--only 挑出 {len(rows)} 票")

    # --limit 截断: 第一次对真系统动手, 先来一票
    if args.limit and args.limit < len(rows):
        rows = rows[:args.limit]
        print(f"--limit {args.limit}: 这次只处理前 {len(rows)} 票"
              f"(csv 里一共 {total} 票)")

    print()

    if not args.go:
        print("=" * 60)
        print("  预览模式 —— 只打印, 不会发任何东西")
        print("  确认无误后加 --go 才会真的建单")
        print("=" * 60 + "\n")
        for row in rows:
            print(json.dumps(build(row), ensure_ascii=False, indent=2))
            print("-" * 60)
        return

    # 真发。把这次的范围再报一遍 —— 这是最后一次能按 Ctrl-C 的地方。
    print("=" * 60)
    print(f"  真的要建单了: 这次 {len(rows)} 票"
          + (f"(csv 共 {total} 票)" if len(rows) != total else ""))
    print(f"  第一票 {rows[0].get('mbl_no','')}"
          + (f"   最后一票 {rows[-1].get('mbl_no','')}" if len(rows) > 1 else ""))
    print("  建错了只能到 GoFreight 里一张张删, 不想发就现在按 Ctrl-C")
    print("=" * 60 + "\n")

    gf = GoFreight()
    created = skipped = failed = 0

    for i, row in enumerate(rows, 1):
        mbl = row.get("mbl_no", "")
        hbl = row.get("hbl_no", "")
        head = f"[{i}/{len(rows)}] {mbl}"

        try:
            # build() 放在 try 里面: 港口格式错、ETA 空这些是 ValueError,
            # 不接住的话一行坏数据会让整批崩在中途, 前面建好的还查不清
            payload = build(row)

            # 先查后建。不查的话第二遍跑就会建出一堆重复的。
            if gf.find_mbl(mbl):
                print(f"{head}  已存在, 跳过")
                log_result(mbl, hbl, "", "已存在")
                skipped += 1
                continue

            data = gf.create_ocean_import_mbl(payload)
            # 保险起见再挡一层: 万一哪天接口又换成别的形状, 也不能在
            # 【单子已经建好】之后崩掉 —— 崩了就丢日志, 比建失败还麻烦
            if isinstance(data, list):
                data = data[0] if data else {}
            ref = data.get("ref", "") if isinstance(data, dict) else ""
            print(f"{head}  建好了  ref={ref}")
            log_result(mbl, hbl, ref, "建好了")
            created += 1

        except ValueError as e:
            # 数据本身有问题(港口不是 LOCODE、ETA 空...), 根本没发出去
            print(f"{head}  数据有问题, 没发: {e}")
            log_result(mbl, hbl, "", f"数据有问题: {e}")
            failed += 1

        except ApiError as e:
            # 一票失败不该拖垮整批, 记下来继续下一票
            print(f"{head}  失败: {e}")
            log_result(mbl, hbl, "", f"失败 {e.status}")
            failed += 1

        except KeyboardInterrupt:
            print("\n手动中断了。已建的那些在 push_log.csv 里。")
            sys.exit(1)

        except Exception as e:
            # 兜底。到这儿说明请求多半已经发出去了, 单子可能【已经建好】。
            # 所以先把这票记下来再抛 —— 日志丢了比程序崩了更难收拾。
            print(f"{head}  没想到的错: {type(e).__name__}: {e}")
            print(f"  !! 这票可能已经建好了, 去查一下:"
                  f"  python lookup.py mbl {mbl}")
            log_result(mbl, hbl, "", f"没想到的错(可能已建好) {type(e).__name__}")
            failed += 1

    print(f"\n完成: 新建 {created}, 跳过 {skipped}, 失败 {failed}")
    print("明细见 push_log.csv")


if __name__ == "__main__":
    main()
