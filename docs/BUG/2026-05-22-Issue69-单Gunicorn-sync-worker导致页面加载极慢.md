# Issue #69 — 单 Gunicorn sync worker 导致页面加载极慢（BUG）

**创建日期**: 2026-05-22  
**关联 Issue**: https://github.com/ZeroPointSix/outlookEmailPlus/issues/69  
**关联模块**: `Dockerfile`、`outlook_web/app.py`、`outlook_web/services/scheduler.py`、`outlook_web/controllers/groups.py`、`outlook_web/controllers/accounts.py`、`outlook_web/controllers/settings.py`、`outlook_web/controllers/system.py`、`static/js/main.js`、`static/js/features/groups.js`、`static/js/features/overview.js`  
**状态**: 🟢 Phase 1 首屏降载已实施完成，待人工验收后进入 Phase 2  
**优先级建议**: P0（影响首屏可用性、健康检查稳定性与生产部署体验）

---

## 1. 背景

- GitHub Issue: `#69 单 gunicorn sync worker 导致页面加载极慢（数分钟）`
- 现象：部署后首屏打开很慢，`/healthz` 健康检查偶发超时，静态资源请求看起来被拖慢。

## 2. 结论摘要

这次问题**不能只归因于 `-w 1` 本身**，实际是以下几类因素叠加放大：

1. **Gunicorn 当前是单个 sync worker**，请求天然串行。
2. **首屏会并发触发多条接口请求**，但在 sync worker 下会退化为排队执行。
3. **部分首屏接口本身不轻**，例如：
   - `/api/settings`
   - `/api/groups`（当前实现含每组计数的 N+1 查询）
   - `/api/accounts?...`
   - `/api/overview/summary`
4. **`/api/system/version-check` 首次命中会同步访问 GitHub API**，虽然有 10 分钟缓存，但冷启动/缓存失效时仍会把单 worker 卡住最多 5 秒。
5. **调度器与 Web 进程仍然耦合在同一 Gunicorn worker 进程内**。这不是“后台任务直接占用 Gunicorn 请求 worker 槽位”，但它强化了“当前部署只能保守地维持单 worker”的架构约束。

## 3. 代码证据

### 1. 当前 Docker 生产启动命令

`Dockerfile`

```dockerfile
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "120", "--access-logfile", "-", "web_outlook_app:app"]
```

当前未显式指定 worker class，因此默认是 **sync**。

### 2. 调度器会在 WSGI 导入阶段自动启动

`outlook_web/app.py`

```python
if scheduler_service.should_autostart_scheduler():
    scheduler_service.init_scheduler(_APP_INSTANCE, graph_service.test_refresh_token_with_rotation)
```

`outlook_web/services/scheduler.py`

```python
scheduler = BackgroundScheduler()
configure_scheduler_jobs(scheduler, app, test_refresh_token)
scheduler.start()
```

这意味着：

- 单进程内 `_scheduler_instance` 可以防重；
- **多 Gunicorn worker 时，每个 worker 仍会各自启动一份 scheduler**。

### 3. 目前不是服务端共享 session 存储

项目仅设置了 Flask 默认 session cookie 相关配置：

```python
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 7
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
```

仓库中没有看到 `Flask-Session` 落地配置。因此“多 worker 会导致 Flask 内存 session 不同步”**不是当前主因**；真正限制多 worker 的是：

1. scheduler 多实例重复执行；
2. 代码中仍有部分“单进程/进程级缓存/模块级状态”假设。

### 4. 首屏请求链路本身较重

`static/js/main.js` 在 `DOMContentLoaded` 期间会触发：

- `/api/csrf-token`
- `/api/settings`
- `/api/groups`
- `/api/tags`
- `/api/overview/summary`
- `/api/system/version-check`

其中 `loadGroups()` 在拿到首个普通分组后，还会继续触发：

- `/api/accounts?group_id=...`

### 5. 几个典型慢点

#### `/api/groups`

`outlook_web/controllers/groups.py` 当前逻辑：

- 先 `load_groups()`
- 再循环调用 `get_group_account_count(group_id)`

即当前是**分组数量级的 N+1 计数查询**。

#### `/api/accounts`

`outlook_web/controllers/accounts.py` / `repositories/accounts.py` 当前会做：

1. `COUNT(*)`
2. 分页主查询
3. hydrate tags
4. 再批量查每个账号最新刷新日志

在账号量大时，这条接口会成为首屏主阻塞项之一。

#### `/api/system/version-check`

会同步访问：

```text
https://api.github.com/repos/ZeroPointSix/outlookEmailPlus/releases/latest
```

虽然内存缓存 TTL 为 10 分钟，但**首次访问和缓存过期后**都会重新走外网请求。

## 4. 为什么会表现成“页面几分钟才打开”

在单 sync worker 下，只要首屏链路里某个请求慢：

1. 后续 HTML/API/静态资源请求全部排队；
2. 浏览器又会并发补发 CSS/JS/icon 等请求；
3. 健康检查 `/healthz` 也必须排队；
4. 于是从用户视角看，就会像“整个站点卡死几分钟”。

## 5. 更深一层的根因拆解

### 5.1 这不是“后台任务直接占满 Gunicorn 请求槽位”的简单模型

当前 APScheduler 运行在 Gunicorn worker 进程内，但它走的是后台线程，不等于“每个 scheduler job 都直接占住一个 Gunicorn HTTP worker 槽位”。

真正的问题是：

1. Web 层只有 **1 个 sync worker**，所有 HTTP 请求必须串行；
2. 首屏又会主动触发多条接口；
3. 其中有几条接口还会做较重的 DB 聚合或外网访问；
4. 所以只要链路里有一条慢，请求队列就会被拉长，最终连 `/healthz` 都被拖住。

换句话说，**单 sync worker 是放大器，不一定是唯一根因，但它把所有慢点都放大成了可用性问题。**

### 5.2 当前首页初始化存在“轻重请求混跑”

从前端启动链路看，首页并没有把“必须首屏返回的请求”和“可延迟请求”分层：

- 必需：`/api/csrf-token`、少量布局/导航数据
- 可延迟：`/api/system/version-check`
- 可分阶段：`/api/overview/*`
- 可用户触发后再查：完整 settings / 某些统计

这会导致首屏阶段把轻请求和重请求一起塞给唯一 sync worker。

### 5.3 当前仓库仍有若干单进程假设

Issue #69 的关键不是“马上加 worker”，而是：

1. scheduler 自动启动逻辑仍绑定在 app 导入期；
2. 文档里仍有“单 worker = 默认前提”的设计假设；
3. 某些缓存与模块级状态尚未按多进程一致性设计。

所以多 worker 不是不能做，而是**现在直接做会把调度器重复执行问题带进来**。

## 6. 推荐缓解路径

### A. 短期缓解（最小改动，优先执行）

1. **保留单 worker 前提下，先做首屏降载**
   - 不在首页初始化时立即调用 `/api/system/version-check`，改成懒加载。
   - `GET /api/groups` 改成单 SQL 聚合计数，去掉 N+1。
   - 仪表盘首屏只拉一个 summary，其他 tab 保持用户点击后再加载。
   - `GET /api/settings` 只返回首屏必需字段，减少“大而全”设置载荷。

2. **给慢但非关键接口加缓存/降频**
   - `version-check`：进程内缓存保留，同时允许完全关闭首屏自动检查。
   - `overview summary`：可考虑 15~60 秒短 TTL 缓存。

3. **给首屏接口做“必须/可延迟”分层**
   - 首页先保证 HTML、静态资源、分组骨架、基础账号列表快速可用；
   - 次级信息（版本检测、深层概览卡片）放到页面稳定后再补。

### B. 中期缓解（部署层改良）

1. **若暂不拆 scheduler，优先尝试单 worker + gevent**
   - 目标：减少请求串行等待，改善静态资源与轻量 API 的排队。
   - 但要注意回归验证 SSE/流式接口、阻塞式库、Monkey Patch 兼容性。

2. **把健康检查保持为最轻路径**
   - 当前 `/healthz` 已经很轻，问题不在 handler 本身，而在排队。
   - 因此健康检查优化重点仍是：降低前台请求排队，而不是继续给 `/healthz` 加逻辑。

### C. 长期正确方案（架构层）

1. **把 APScheduler 从 Web 进程拆出去**
   - 单独 scheduler 进程 / sidecar / 独立容器。
2. **Web 侧再安全提升为多 worker**
   - 这样才能真正摆脱“所有请求串行”的结构性瓶颈。
3. **逐步清理单进程假设**
   - 进程级缓存
   - 模块级状态
   - 依赖单 worker 的设计文档约束

## 7. 建议执行顺序（我当前最推荐）

若目标是“先把线上卡顿压下来”，建议执行顺序：

1. 首屏降载（version-check 懒加载、groups 去 N+1、settings 瘦身）
2. 再评估 gevent 单 worker
3. 最后推进 scheduler 拆分 + 多 worker

### 7.1 推荐排序

1. **先改首屏降载**
2. **再做 gevent 兼容性验证**
3. **最后拆 scheduler，再开放多 worker**

### 7.2 为什么不是直接上 gevent

因为 gevent 能缓解排队，但不能消灭下面这些问题：

- `/api/groups` 的 N+1
- `/api/settings` 首屏过肥
- `/api/system/version-check` 冷缓存外网调用
- scheduler 与 Web 进程耦合

所以 gevent 更像是**第二层缓冲垫**，不是第一修复位点。

## 8. 建议观测指标（修复前后都应采）

### 8.1 用户侧指标

1. 首页首包时间（TTFB）
2. 首屏可交互时间
3. 仪表盘首屏完整加载时间

### 8.2 服务侧指标

1. `/healthz` 成功率与 P95
2. `/api/groups`、`/api/accounts`、`/api/settings`、`/api/overview/summary` 的 P50 / P95
3. Gunicorn access log 中等待明显拉长的接口

### 8.3 架构侧指标

1. scheduler 心跳是否稳定
2. 是否出现重复 job 执行痕迹
3. 冷缓存下 `version-check` 的请求频次与耗时

## 9. 验证思路

### 9.1 首屏降载完成后的验收标准

1. 冷启动打开首页，不再出现“多个基础静态资源明显排队数十秒”现象
2. `/healthz` 在页面打开期间仍能稳定返回 200
3. `/api/groups`、`/api/settings`、`/api/accounts` 的 P95 明显下降
4. 首页在未完成 version-check 时也能先可用

### 9.2 gevent 评估时必须验证的兼容项

1. SSE/流式接口是否仍能及时 flush
2. 批量刷新/长连接接口是否出现新阻塞行为
3. 第三方库（`requests`、SQLite、调度线程）是否出现兼容性回归

### 9.3 scheduler 拆分后的验收标准

1. Web worker 数量提升后不再重复注册 scheduler jobs
2. 通知分发 / probe poll / pool maintenance 只执行一次
3. 首页与健康检查在并发下稳定

## 10. 风险与约束

| 风险/约束 | 说明 |
|---|---|
| 直接加多 worker | 会先引入 scheduler 重复执行问题 |
| 直接切 gevent | 可能引入 SSE flush、猴补丁兼容性回归 |
| 只做部署层优化 | 无法消除首屏慢接口本身的负担 |
| 只做代码层轻优化 | 若仍保留 sync 单 worker，峰值排队问题仍可能存在 |

## 11. 不应继续坚持的错误前提

1. **“只要是单 worker 就一定安全”** → 错。当前它已经明显伤害可用性。
2. **“多 worker 的主要问题是 session 不同步”** → 对本仓库现状并不准确。
3. **“健康检查超时说明 /healthz 本身慢”** → 大多数情况下是被排队拖慢。

## 12. 本文档用途

本分析用于：

- 回填 Issue #69 的技术背景；
- 修正仓库内“单 worker 是稳定前提”的过强表述；
- 作为后续性能优化与部署演进的依据。
