"""
拿到 key 之后【第一个】跑这个。

它只读不写, 跑错了也不会在系统里留下任何东西,
所以是最安全的一步: 先确认 key 能用、网络通得了, 再谈建单。
"""

import os

from gofreight import GoFreight, ApiError, BASE

# 建单要用到的几个设置。漏设一个的后果差别很大, 所以这里分成
# 【必填】和【选填】两类, 一眼能看出哪个真的会出事。
SETTINGS = [
    ("GOFREIGHT_API_KEY", True, "API key 本身"),
    ("GOFREIGHT_OFFICE_REF", True, "办公室编号, 跑 lookup.py offices 查"),
    ("GOFREIGHT_PACKAGE_UNIT_REF", False, "件数单位, 一般是 CT(CARTON(S))"),
    ("GOFREIGHT_OVERSEA_AGENT_REF", False,
     "Oversea Agent 的 TP 编号, 比如 CHINA ARTS"),
    ("GOFREIGHT_CY_LOCATION_REF", False,
     "CY Location 的 TP 编号, 比如 FENIX MARINE (Y257)"),
]


def show_settings():
    print("设置:")
    missing_required = False
    for name, required, what in SETTINGS:
        v = os.environ.get(name)
        if v:
            # key 不能打出来, 只给个长度让人确认不是空的
            shown = f"(已设, {len(v)} 位)" if "KEY" in name else v
            print(f"  ✓ {name} = {shown}")
        elif required:
            print(f"  ✗ {name} 没设  <- 必须有: {what}")
            missing_required = True
        else:
            print(f"  - {name} 没设  ({what}) -> 这一栏会留空")
    if missing_required:
        print("\n  PowerShell 里这样设, 设完【重开一个窗口】:")
        print('    [Environment]::SetEnvironmentVariable("名字","值","User")')
    print()


show_settings()
print(f"接口地址: {BASE}")
print("正在用 key 查一下主单列表...\n")

try:
    gf = GoFreight()
    rows = gf.find_mbl("__这个号肯定不存在__")
    print("认证通过 ✓")
    print(f"查询正常返回, 匹配到 {len(rows)} 票(查的是一个假号, 0 票才对)")
    # 顺手把办公室名字打出来 —— 这是分辨【沙箱还是真系统】最快的办法。
    # 两边的 office_ref 都可能是 1, 但名字不一样。
    ref = os.environ.get("GOFREIGHT_OFFICE_REF")
    if ref:
        try:
            hit = [o for o in (gf.offices() or {}).get("data", [])
                   if str(o.get("ref")) == str(ref)]
            if hit:
                o = hit[0]
                print(f"\n这把 key 连的是: {o.get('full_name') or o.get('local_name')}"
                      f"  (office_ref={ref})")
                if o.get("is_active") is False:
                    print("  !! 这个办公室是【停用】的, 建单多半会被拒")
            else:
                print(f"\n!! 这个账号下没有 office_ref={ref} 这个办公室 ——"
                      f" 换过 key 吗? 跑 lookup.py offices 重新挑一个")
        except ApiError:
            pass

    # TP 编号必须验。它是租户自己的编号, 换个账号就是另一家公司 ——
    # 填错了不一定报错, 可能就安静地挂上了【别人家】的代理。
    for name, what in (("GOFREIGHT_OVERSEA_AGENT_REF", "Oversea Agent"),
                       ("GOFREIGHT_CY_LOCATION_REF", "CY Location")):
        ref = os.environ.get(name)
        if not ref:
            continue
        try:
            tp = gf.trade_partner(ref.strip())
        except ApiError as e:
            print(f"\n{what} {ref}: 查不了 ({e.status})")
            continue
        if tp:
            print(f"\n{what} {ref} = "
                  f"{tp.get('full_name') or tp.get('local_name') or tp}")
            if tp.get("is_active") is False:
                print("  !! 这家是【停用】的")
        else:
            print(f"\n!! {what} {ref} 在这个账号里【不存在】")
            print(f"   这个编号多半是从别的租户(真系统)抄来的。")
            print(f"   跑  python lookup.py partners 关键字  找这个账号自己的编号,")
            print(f"   或者把 {name} 删掉 —— 这一栏留空也能建单。")

    print("\n下一步可以跑:  python fields.py")

except ApiError as e:
    if e.status == 401:
        print("认证失败 (401) —— key 不对, 或者没设对环境变量")
    elif e.status == 403:
        print("认证过了但没权限 (403) —— 这把 key 可能没开这个接口")
    else:
        print(f"接口报错: {e}")

except Exception as e:
    print(f"连不上: {e}")
    print("检查一下网络, 或者公司网络是不是挡了外网")
