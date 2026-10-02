# gridpromo — 网格促销位排期库

供上层陈列服务调用的 Python 库，排期数据持久化在本地 SQLite 文件中，无接口层、无外部服务依赖。

## 功能

- 创建网格：行列数、每格位默认商品（可为空）、IANA 时区（创建后不可改）
- 促销排期：新建、改期、取消；时间按网格时区的 12 小时制本地时间填写（`MM/DD/YYYY HH:MM AM/PM`，精确到分钟）
- 展示查询：任意实际时刻下，生效促销格位显示促销商品，其余显示默认商品

## 业务规则

- 生效区间为 `[start, end)`：含开始、不含结束，首尾相接不算重叠；结束必须晚于开始（按实际时间比较）
- 夏令时空档中不存在的本地时间，按空档结束时刻算（如纽约 `03/08/2026 02:30 AM` → 当天 03:00 EDT）
- 秋季回拨重复时间：作开始取第一次出现，作结束取第二次出现
- 同一网格任意时刻生效促销 ≤ 20；同一格位任意时刻 ≤ 1
- 新建/改期违反约束即整单拒绝；改期被拒时原排期不变；取消后名额立即释放

## 用法

```python
from datetime import datetime, timezone
from gridpromo import GridPromoService

svc = GridPromoService("promo.db")          # 本地 SQLite 文件；":memory:" 为纯内存
svc.create_grid("grid-1", rows=6, cols=5, timezone="America/New_York",
                default_products={(0, 0): "SKU-DEFAULT"})

svc.schedule("grid-1", "promo-1", row=1, col=1, product_id="SKU-X",
             start_local="03/08/2026 12:00 AM", end_local="03/08/2026 04:00 AM")
svc.reschedule("grid-1", "promo-1", "03/08/2026 01:30 AM", "03/08/2026 03:30 AM")
svc.cancel("grid-1", "promo-1")

board = svc.display_at("grid-1", datetime.now(timezone.utc))  # 返回 rows×cols 的嵌套列表
svc.close()
```

异常：`ConflictError`（越界/冲突被拒）、`InvalidTimeError`（时间格式或先后非法）、
`GridNotFoundError` / `PromotionNotFoundError`、`GridPromoError`（其余，如网格已存在、格位越界）。

## 测试

```bash
python3 -m pytest tests/ -q
```

覆盖：纽约时区春/秋两次夏令时切换日的新建、改期、取消（逐分钟比对实际生效分钟）、
30 格位同时段恰好 20 成功 10 被拒、取消释放名额、持久化重开等。

## 结构

- `gridpromo/timeparse.py` — 本地时间解析与 DST 规则（空档取空档结束、重复取第一/二次）
- `gridpromo/store.py` — SQLite 持久化（时间统一存 epoch 秒，事务保证检查+写入原子）
- `gridpromo/service.py` — 业务逻辑（扫描线求最大并发数做容量校验）
- `gridpromo/errors.py` — 异常类型
