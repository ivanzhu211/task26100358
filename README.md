# task26100358

## gridpromo：网格促销位排期库

纯 Python + SQLite 的排期模块，供上层陈列服务以库的方式调用，无接口层。

### 用法

```python
from datetime import datetime, timezone
from gridpromo import GridService, connect

svc = GridService(connect("promo.db"))  # 本地 SQLite 文件，":memory:" 亦可

grid_id = svc.create_grid(
    rows=4, cols=5,
    timezone="America/New_York",          # IANA 时区，创建后不可改
    default_products={(0, 0): "SKU-1"},   # 缺省为 None
)

promo_id = svc.create_promo(
    grid_id, row=0, col=0, product="SKU-9",
    start_local="03/08/2026 02:30 PM",    # 网格时区 12 小时制本地时间
    end_local="03/08/2026 04:00 PM",
)
svc.reschedule_promo(promo_id, "03/08/2026 03:00 PM", "03/08/2026 05:00 PM")
svc.cancel_promo(promo_id)

board = svc.get_display(grid_id, datetime(2026, 3, 8, 19, 0, tzinfo=timezone.utc))
# board[row][col] -> CellView(product, is_promo, promo_id)
```

### 规则要点

- 生效区间为 `[start, end)`，首尾相接不算重叠；结束必须晚于开始（按实际时间比较）。
- 夏令时空档里不存在的本地时间按空档结束时刻算（如纽约 `03/08/2026 02:30 AM` 按 03:00 EDT）。
- 秋季回拨重复的本地时间：开始取第一次出现，结束取第二次出现。
- 同一网格任意时刻生效促销不超过 20 个；同一格位任意时刻最多一个。
  新建/改期越界则整单拒绝（`ConflictError`），改期被拒时原排期不变。

### 测试

```bash
python3 -m pytest tests/ -q
```
