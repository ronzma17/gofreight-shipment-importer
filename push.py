"""
主程序: 读 CSV, 一票一票建进 GoFreight。

默认【只打印不发送】。要真发必须显式加 --go。
写这类批量写入的脚本我一定留这个开关 —— 宁可多敲四个字母,
也不要手一抖把几十票垃圾数据灌进系统, 删起来比建起来难受得多。

用法:
    python push.py examples/shipments.csv          只看 JSON, 不发
    python push.py examples/shipments.csv --go     真发
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
    args = ap.parse_args()

    rows = read_rows(args.csv_file)
    print(f"读到 {len(rows)} 票\n")

    if not args.go:
        print("=" * 60)
        print("  预览模式 —— 只打印, 不会发任何东西")
        print("  确认无误后加 --go 才会真的建单")
        print("=" * 60 + "\n")
        for row in rows:
            print(json.dumps(build(row), ensure_ascii=False, indent=2))
            print("-" * 60)
        return

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
            ref = (data or {}).get("ref", "")
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

    print(f"\n完成: 新建 {created}, 跳过 {skipped}, 失败 {failed}")
    print("明细见 push_log.csv")


if __name__ == "__main__":
    main()
