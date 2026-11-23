"""
拿到 key 之后【第一个】跑这个。

它只读不写, 跑错了也不会在系统里留下任何东西,
所以是最安全的一步: 先确认 key 能用、网络通得了, 再谈建单。
"""

from gofreight import GoFreight, ApiError, BASE

print(f"接口地址: {BASE}")
print("正在用 key 查一下主单列表...\n")

try:
    gf = GoFreight()
    rows = gf.find_mbl("__这个号肯定不存在__")
    print("认证通过 ✓")
    print(f"查询正常返回, 匹配到 {len(rows)} 票(查的是一个假号, 0 票才对)")
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
