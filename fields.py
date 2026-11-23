"""
看看这个账号有哪些自定义字段。

也是只读的。建单之前跑一次, 免得建完才发现有几个必填的自定义字段没填。
"""

import json
from gofreight import GoFreight, ApiError

try:
    data = GoFreight().custom_fields()
    print(json.dumps(data, ensure_ascii=False, indent=2))
except ApiError as e:
    print(f"读不到: {e}")
