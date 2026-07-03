# Issue #69 — gevent 单 worker 兼容性评估报告

> 创建日期: 2026-05-22
> 关联 Issue: https://github.com/ZeroPointSix/outlookEmailPlus/issues/69
> 目的: 在不立刻拆 scheduler 的前提下，评估 gevent 单 worker 是否值得作为部署层的中间缓解方案
> 结论: **建议跳过 gevent，优先进入 Phase 4 scheduler 拆分**

---

## 1. gevent 切换前置条件

### 1.1 需新增依赖

- `gevent>=24.2.0` 添加到 `requirements.txt`
- Gunicorn worker class 改为 `gevent`：`gunicorn -w 1 -k gevent`

### 1.2 Dockerfile 变更

```dockerfile
# 当前
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "120", "--access-logfile", "-", "web_outlook_app:app"]

# gevent 方案
CMD ["gunicorn", "-w", "1", "-k", "gevent", "-b", "0.0.0.0:5000", "--timeout", "120", "--access-logfile", "-", "web_outlook_app:app"]
```

需在应用入口 `web_outlook_app.py` 或 gunicorn 配置中最先执行 `monkey.patch_all()`。

### 1.3 Monkey Patching 策略

有两种策略：

| 策略 | 命令 | 风险 |
|------|------|------|
| A: 全面 patching | `patch_all()` | APScheduler 线程被替换为 greenlet |
| B: 仅 patch socket | `patch_all(thread=False)` | scheduler 线程保持原生，但锁竞态存疑 |

### 1.4 受影响接口类型

| 接口类型 | 文件 | 影响评估 |
|----------|------|----------|
| SSE 流式刷新 | `controllers/accounts.py` (3 端点: refresh_all / scheduled / selected) | gevent 可处理 yield 流 |
| REST JSON API | 全部 `/api/*` 端点 | 非阻塞，受益最大 |
| 外网 HTTP 调用 | `controllers/system.py` (version-check/watchtower/docker) | urllib 被 patch 后非阻塞 |
| 线程池并发 | `services/telegram_push.py`, `services/imap.py` | `ThreadPoolExecutor` 需验证 |
| 调度器后台 Job | `services/scheduler.py` | **主要风险面** |

---

## 2. 兼容性风险清单

### 2.1 APScheduler BackgroundScheduler (🔴 高风险)

**现状**：`BackgroundScheduler` 在 Gunicorn worker 进程内以独立线程运行，通过 `atexit` 注册 shutdown。

**风险**：
- 策略 A (`patch_all()`)：`BackgroundScheduler` 内部依赖 `threading.Thread` 和 `threading.Event`。Patch 后线程变成 greenlet，但 APScheduler 的定时触发器（`CronTrigger`/`IntervalTrigger`）依赖 `time.sleep()` 计算，这可能被 gevent 的 `sleep(0)` 交换机打断。
- 策略 B (`patch_all(thread=False)`)：scheduler 线程保持原生，但此时进程内同时存在 greenlet 协程和原生线程。SQLite 连接在两种执行模式下共享，存在锁竞态风险。

**具体影响**：
- 调度器 6 个 job (heartbeat / notification_dispatch / probe_poll / pool_expire / pool_recover / token_refresh) 可能全部受影响
- token_refresh 内部使用 `time.sleep(delay_seconds)` (scheduler.py:555)，被 patch 后可能产生非预期行为

### 2.2 ThreadPoolExecutor (🟡 中风险)

**现状**：
- `services/telegram_push.py:615` — `ThreadPoolExecutor(max_workers=min(len(normalized_accounts), 10))`
- `services/imap.py:552` — `ThreadPoolExecutor(max_workers=len(servers))`

**风险**：`ThreadPoolExecutor` 在 patch 后 worker 变为 greenlet，`as_completed` 可能失序或死锁。

### 2.3 threading.Lock (🟡 中风险)

**现状**：
- `services/oauth_tool.py:24` — `threading.Lock`
- `services/imap.py:29` — `threading.Lock` (token 缓存)
- `services/channel_capability_cache.py:11` — `threading.Lock`

**风险**：`threading.Lock` 被 monkey patch 替换为 gevent 的 `BoundedSemaphore`。正常情况下绿色线程间的锁行为等价，但高并发下的公平性可能变化。

### 2.4 SSE 流式接口 (🟢 低风险)

**现状**：3 个 SSE 端点全部使用 yield 模式：
```python
def stream_refresh_all(...) -> Iterator[str]:
    ...
    yield f"data: {json.dumps({...})}\n\n"
    ...
```
响应 `mimetype="text/event-stream"`。

**兼容性**：gevent 对 Python 生成器协程天然友好，yield 语义不变。唯一需要验证的是浏览器端 `EventSource` 重连逻辑不会因 gevent 的 socket 行为变化导致意外断开。

### 2.5 urllib.request 外网调用 (🟢 低风险)

**现状**：`system.py` 使用 `urllib.request.urlopen()` 访问 GitHub API、Watchtower、Docker API。

**兼容性**：monkey patching 后 `urllib.request` 的 socket 层被替换为非阻塞 I/O，这是 gevent 的标准收益场景。但需注意 `timeout` 参数的语义变化——gevent 下超时会触发 `gevent.timeout.Timeout`。

### 2.6 SQLite WAL 模式 (🟡 中风险)

**现状**：SQLite WAL 模式，请求线程和调度器线程共享同一数据库文件。

**风险**：gevent 下，多个 greenlet 共享同一线程但 SQLite 连接不是 greenlet-safe 的。每个请求使用 `get_db()` 获取请求级连接（Flask `g`），这不是问题。但调度器 job 内部创建独立连接（`create_sqlite_connection()`），可能与请求共享的连接在文件层面产生锁等待。WAL 模式已大幅降低此风险，但仍需验证。

---

## 3. 验证方案设计

### 3.1 最小验证矩阵

| 验证项 | 方法 | 通过标准 |
|--------|------|----------|
| 首页加载 | 浏览器打开首页 | 正常渲染，无 5XX |
| SSE 流式刷新 | 触发"刷新所有 token" | 流式输出完整，浏览器 EventSource 无断连 |
| 调度器心跳 | 检查 `settings` 表 `scheduler_heartbeat` | 60 秒内更新 |
| 通知分发 | 检查 `notification_delivery_logs` 表 | 有正常记录 |
| 邮箱池维护 | 检查 `account_claim_logs` 表 | expire/recover 正常执行 |
| ThreadPool 并发 | 触发 TG 推送 + IMAP 刷新 | 无死锁，结果完整 |
| 静态资源 | 浏览器 Network 面板 | CSS/JS 正常加载 |

### 3.2 必过回归清单

1. 全量 unittest：1454 cases, 0 new failures
2. `python -m unittest tests.test_settings_scheduler_reload` — 调度器重载
3. 手动验证：首页 → 登录 → 分组 → 账号列表 → 刷新 → 概览 → 设置
4. 手动验证：多 tab 并发请求是否不再明显排队

### 3.3 建议验证环境

本地 Docker 构建 + `docker run -p 5000:5000`，使用测试数据库，避免影响生产。

---

## 4. 结果决策

### 4.1 风险汇总

| 风险项 | 等级 | 可缓解性 | 缓解措施 |
|--------|------|----------|----------|
| APScheduler 线程 | 🔴 高 | 低 | 需拆 scheduler 或深度测试 |
| ThreadPoolExecutor | 🟡 中 | 中 | 限制 worker 数 + 加超时 |
| threading.Lock | 🟡 中 | 中 | 改为 `gevent.lock` 或加超时 |
| SQLite 共享 | 🟡 中 | 高 | WAL 模式已天然缓解 |
| SSE/yield | 🟢 低 | — | 无需处理 |
| urllib 外网 | 🟢 低 | — | 标准收益 |

### 4.2 决策：建议跳过 gevent，直接进入 Phase 4

**理由**：

1. **gevent 能缓解但不能消灭问题**：gevent 可以让轻请求（静态资源/csrf-token/bootstrap）不再被重请求阻塞，但不能消灭重请求本身的开销（groups 聚合/settings 解密/version-check 外网）。
2. **Phase 1+2 已大幅降低首屏负载**：经过首屏降载 + 缓存优化后，当前的瓶颈已从"请求并发排队"转移到"单请求本身的计算/IO 开销"。
3. **gevent 引入的调度器风险 > 预期收益**：APScheduler + monkey patch 的组合风险较高，且没有现成的兼容性测试覆盖。
4. **正确的演进路径**：先拆 scheduler (Phase 4) → 再安全地多 worker 或 gevent。

### 4.3 如果仍然选择 gevent

若团队决策仍然要尝试 gevent，最低限度应：
1. 使用策略 B: `monkey.patch_all(thread=False, ssl=True, socket=True)`
2. 在 staging 环境全量跑 1454 tests，新增 scheduler 稳定性专项测试
3. 至少观察 48 小时：心跳是否间断、job 是否重复执行、SSE 是否断连

---

## 5. 替代方案

### 5.1 立即可用：Phase 1+2 已实施

- version-check 延迟 5s
- groups 去 N+1
- bootstrap 轻量端点替代 settings
- overview summary 30s TTL
- **效果**：单 sync worker 下的排队放大效应已显著降低

### 5.2 短期：Phase 4 scheduler 拆分

- 独立 scheduler 进程/sidecar
- 之后安全使用 `gunicorn -w 2` (sync) 即可
- 无需引入 gevent 生态

### 5.3 中期：多 worker + gevent

- 仅在 scheduler 拆出后评估
- 此时 gevent 的风险面已从"scheduler 耦合"缩小到"ThreadPool 验证"

---

## 6. 附录：受影响的代码位置

| 文件 | 相关代码 | 风险类别 |
|------|----------|----------|
| `services/scheduler.py:342-362` | `BackgroundScheduler()` 初始化 | 线程/调度 |
| `services/scheduler.py:555` | `time.sleep(delay_seconds)` | 阻塞 |
| `services/telegram_push.py:615` | `ThreadPoolExecutor` | 线程池 |
| `services/imap.py:552` | `ThreadPoolExecutor` | 线程池 |
| `services/oauth_tool.py:24` | `threading.Lock` | 锁 |
| `services/imap.py:29` | `threading.Lock` | 锁 |
| `services/channel_capability_cache.py:11` | `threading.Lock` | 锁 |
| `controllers/accounts.py:2399-2805` | SSE 流式刷新 (3 端点) | 流 |
| `controllers/system.py:420-467` | `urllib.request` 版本检查 | I/O |
| `controllers/system.py:508-654` | `urllib.request` Watchtower/Docker | I/O |
