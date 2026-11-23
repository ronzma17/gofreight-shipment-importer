"""
把一行 CSV 翻译成 API 要的 JSON。

单独放一个文件, 是因为这部分【不用联网就能测】——
改完直接打印出来看对不对, 不用等 key、不用发请求。
"""


def split(v):
    """多柜的票柜号是逗号连在一格里的, 拆成列表。

       'ABCD1234567,EFGH7654321'  ->  ['ABCD1234567', 'EFGH7654321']
    """
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def build(row):
    """CSV 的一行 -> 建单用的 JSON

       !! 重要 !!
       下面这些字段名是照 GoFreight 文档的示例写的, 还没有逐个核对过。
       第一次真发之前, 去 redoc 把 ocean-import/mbl 的完整 schema 对一遍,
       以那边为准。猜错一个必填字段, 整批都会失败。
    """
    containers = split(row.get("container_no"))
    seals      = split(row.get("seal_no"))
    sizes      = split(row.get("size_type"))

    container_list = []
    for i, no in enumerate(containers):
        container_list.append({
            "container_no": no,
            # 封条和柜型可能比柜号少(比如只填了一个), 所以用下标防越界,
            # 取不到就留空, 不要让整票因为缺一个封条就建不进去
            "seal_no":   seals[i] if i < len(seals) else "",
            "size_type": sizes[i] if i < len(sizes) else "",
        })

    payload = {
        "mbl_no":            row["mbl_no"],
        "port_of_loading":   row.get("pol", ""),
        "port_of_discharge": row.get("pod", ""),
        "container_list":    container_list,
    }

    # 分单号有才加。没有 HBL 的票也是存在的, 别硬塞一个空的进去
    if row.get("hbl_no"):
        payload["hbl_list"] = [{"hbl_no": row["hbl_no"]}]

    # 件数重量这些是可选的, 有就带上
    for csv_name, api_name in [
        ("pieces", "pieces"),
        ("weight", "weight"),
        ("measurement", "measurement"),
        ("eta", "eta"),
    ]:
        if row.get(csv_name):
            payload[api_name] = row[csv_name]

    return payload


# 直接跑这个文件 = 拿样例数据打印一条 JSON 出来看看
if __name__ == "__main__":
    import csv
    import json
    import sys
    from pathlib import Path

    path = sys.argv[1] if len(sys.argv) > 1 else "examples/shipments.csv"
    with open(Path(path), encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            print(json.dumps(build(row), ensure_ascii=False, indent=2))
            break        # 只看第一条就够了
