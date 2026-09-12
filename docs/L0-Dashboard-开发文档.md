# L0 数据底座控制台（Dashboard）开发文档

> 交付对象：Codex / 开发同学
> 目标：把「可交互、有数据、样式精致」的运维控制台正式落地到**真实后端** `dashboard.py`，统一目前分叉的两套前端。
> 文档版本：v1.0 · 2026-06-04

---

## 0. 背景与现状

L0 数据底座当前的 `dashboard.py` 是一个 **只读监控页**，只有 `GET /` 和 `GET /api/status`，没有任何写操作、不能翻页、样式简陋。

本期要把它升级成 **可操作的运维控制台**：能新增采集来源、手动触发抓取、启用/停用来源，任务列表可翻页，并使用统一的精致 UI（浅色/深色双主题）。

### 已有可复用资产
- **交互+样式参考稿（含模拟后端）**：`docs/dashboard-live-preview.html`
  这是一份**自包含**的设计与交互原型：内置 mock 数据、拦截 `fetch('/api/*')`、所有按钮可点。**前端的视觉与交互以它为准**，开发时把其中的「模拟后端 IIFE」删掉、换成真实接口即可。
- **真实后端入口**：`src/core_data/scripts/dashboard.py`，HTML 模板：`src/core_data/scripts/dashboard.html`
- **可复用的领域函数（不要重复造轮子）**：
  - `core_data.sources.repository.create_source(session, *, name, feed_url, home_url=None, source_type="article", crawl_config=None) -> Source`（**重复 feed_url 会抛 `ValueError`**）
  - `core_data.ingest.pipeline.crawl_source(session, object_store, source, *, fetch_media=False) -> dict[str,int]`（返回 `{"entries","raw","content","failed","media"}`）
  - `core_data.storage.factory.build_object_store(settings)`、`core_data.config.get_settings()`
  - 模型：`Source / ContentItem / CrawlJob / OutboxEvent / RawDocument`（见 `core_data/db/models.py`）

### 关键不变量（**必须遵守，违反即不通过**）
1. **不得破坏 L0 既有契约**：`raw_documents` 仅可 append；不得在 dashboard 里 update/delete 原始层。
2. **不得越层 import**：dashboard 只能依赖 `core_data.*`，不得引入 L1+ 模块。
3. **稳定事件/字段不变**：`content.ingested {content_id, lang}`；L1 稳定字段 `id, canonical_url, title, clean_text, lang, source, published_at, status` 不受影响。
4. 现有测试、`ruff`、`mypy`、`audit_dod` 全部保持绿。

---

## 1. 范围（Scope）

### In scope
- 后端：在 `dashboard.py` 中新增 4 个接口（见 §2），并为 `/api/status` 增加分页与 `deltas`/`dedup` 字段。
- 前端：将 `dashboard-live-preview.html` 的 UI/交互正式合并进 `dashboard.html`（真实接口、删除 mock）。
- 自测：单元测试 + 手动冒烟（见 §5、§6）。

### Out of scope
- 鉴权/多用户权限（本期单机运维，默认 `127.0.0.1` 绑定即可，文档 §7 注明风险）。
- 抓取任务的异步队列化（本期同步触发即可，但需超时与错误兜底）。
- 来源的编辑/删除（仅新增 + 启用停用）。

---

## 2. 后端接口契约（API Contract）

所有响应 `Content-Type: application/json; charset=utf-8`；错误统一返回 `{"error": "<message>"}` 并配合恰当 HTTP 状态码。

### 2.1 `GET /api/status`
查询参数：
| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `jobs_offset` | int ≥0 | 0 | 任务分页偏移（非法值回退默认）|
| `jobs_limit` | int | 8 | 任务每页条数，服务端 clamp 到 `[1,100]` |

响应体（字段全部必填，除非标注 optional）：
```jsonc
{
  "generated_at": "2026-06-04T12:00:00",
  "counts": {
    "sources": 12,            // Source 总数
    "raw_documents": 3481,    // RawDocument 总数
    "content_items": 1907,    // ContentItem 总数
    "outbox_events": 1884,    // OutboxEvent 总数
    "outbox_pending": 23      // OutboxEvent where published_at IS NULL
  },
  "deltas": { "raw": 146, "content": 72 },   // 近 24h 新增（见下）
  "sources": [
    { "id": 1, "name": "Rust Blog", "feed_url": "https://...", "enabled": true }
  ],
  "recent_content": [
    { "id": 1907, "title": "…", "canonical_url": "https://…",
      "lang": "en", "status": "WAIT_FILTER", "fetched_at": "…" }
  ],
  "recent_jobs": [
    { "id": 8841, "source_id": 1, "kind": "rss", "status": "succeeded",
      "started_at": "…", "stats": {"entries":5,"raw":10,"content":5,"failed":0}, "error": null }
  ],
  "jobs_page": { "offset": 0, "limit": 8, "total": 42,
                 "has_prev": false, "has_next": true },
  "dedup": { "unique": 1612, "variant": 221, "duplicate": 74 }   // 见下
}
```
计算口径：
- `sources` 按 `created_at desc` 取最多 50 条；`recent_content` 按 `fetched_at desc` 取 12 条；`recent_jobs` 按 `started_at desc`，`offset/limit` 分页。
- `deltas.raw` = 近 24h 内 `RawDocument.fetched_at >= now-24h` 的计数；`deltas.content` = 近 24h 内 `ContentItem.fetched_at >= now-24h` 的计数。
- `dedup`：按 `ContentItem.status` 归类计数——`variant` = status 含 `VARIANT`，`duplicate` = status 含 `DUP`/`DUPLICATE`，`unique` = 其余。**若现有 status 取值不含这些枚举，可改为：`unique=content_items 总数`、`variant=0`、`duplicate=0`，并在 PR 描述里说明实际取值来源。**
- `jobs_page.has_next` = `offset + limit < total`；`has_prev` = `offset > 0`。

### 2.2 `POST /api/sources`  — 新增来源
请求体：`{ "name": "Rust Blog", "feed_url": "https://...", "home_url": "https://..." }`
- `name` 必填且去空白后非空，否则 `400 {"error":"name is required"}`。
- `feed_url`/`home_url` 可空（空串视为 `null`）。
- 复用 `create_source(...)`；**重复 feed_url 抛 `ValueError` → 返回 `400 {"error":"duplicate feed_url: ..."}`**。
- 成功：`201`，返回 `{ "id", "name", "feed_url", "enabled" }`，并 `session.commit()`。

### 2.3 `POST /api/sources/toggle` — 启用/停用
请求体：`{ "id": 4 }`
- `id` 必须为整数，否则 `400`。
- 来源不存在 → `400 {"error":"source 4 not found"}`。
- 翻转 `enabled` 并 commit，返回 `{ "id", "enabled" }`。

### 2.4 `POST /api/crawl` — 手动触发抓取
请求体：`{ "source_id": 1 }`
- `source_id` 必须为整数，否则 `400`；来源不存在 → `400`。
- 复用 `crawl_source(session, object_store, source)`，成功后 commit。
- 成功：`200 {"source_id":1,"stats":{...}}`。
- **失败兜底**：`crawl_source` 内部异常（如来源无 `feed_url`、网络错误）须捕获并返回 `500 {"error":"<原因>"}`，不可让连接 500 无 body 或进程崩溃。
- 注意该接口是**同步阻塞**的；前端会显示「抓取中…」。服务端用 `ThreadingHTTPServer`，单次抓取阻塞当前线程可接受。

### 错误处理统一约定
- `do_POST` 中：`ValueError` → `400`；其他 `Exception` → `500`；路径未命中 → `404`。
- 所有进入 HTML 的动态文本必须在前端转义（已有 `esc()`），后端 JSON 用标准序列化。

---

## 3. 前端要求（以 `dashboard-live-preview.html` 为准）

### 3.1 布局
- 顶部 App Bar：Logo「L0」+ 标题、搜索框、🌙主题切换、**＋新增来源** 按钮。
- 指标卡 ×5：采集来源 / 原始文档 / 规范内容 / Outbox 事件 / 待发布（待发布为 0 显示绿色，>0 显示告警色）。
- 第一行：`最近内容`（表格 + 状态筛选 chips：全部/READY/WAIT_FILTER/VARIANT/FAILED） | `采集来源`（头像 + feed + 健康度条 + 每行「抓取 / 启用停用」按钮）。
- 第二行：`最近抓取任务`（表格 + 底部「上一页/下一页」+「第 X–Y 条 / 共 N 条」） | `Outbox & 去重`（投递率进度条 + 唯一/变体/重复分布）。
- 右下角 toast 提示；新增来源用居中弹窗（含 ESC/点遮罩关闭）。

### 3.2 交互
| 操作 | 行为 |
|---|---|
| 新增来源 | 打开弹窗→校验 name→`POST /api/sources`→成功 toast + 关闭弹窗 + `refresh()` |
| 立即抓取 | 行内按钮（无 feed_url 时 `disabled`）→ toast「抓取中…」→`POST /api/crawl`→完成 toast(raw/content/failed) + `refresh()` |
| 启用/停用 | `POST /api/sources/toggle`→ toast + `refresh()` |
| 任务翻页 | 维护 `jobsOffset`，调 `GET /api/status?jobs_offset=&jobs_limit=`，边界自动禁用按钮 |
| 状态筛选 / 搜索 | 纯前端过滤 `recent_content`（不打后端）|
| 主题切换 | `data-theme` 切换，写入 `localStorage` |

### 3.3 必须保留的健壮性细节（**这些是本期排障得出的硬要求**）
1. **请求序号守卫**：`refresh()` 用自增 `seq`，仅渲染最后一次请求的响应，丢弃过期响应，避免乱序覆盖。
2. **自动刷新与操作不抢渲染**：定时轮询（建议 10s）在**弹窗打开时暂停**；用户主动操作后的 `refresh()` 必须能即时生效。
3. **来源行用事件委托**（监听容器而非每个按钮），保证 `innerHTML` 重渲染后仍可点击。
4. 所有动态文本 `esc()` 转义防 XSS。
5. fetch 失败时在状态栏给出可见错误，不可静默。

---

## 4. 验收标准（Definition of Done）

> 全部满足才算完成。建议在 PR 描述里逐条打勾并贴证据。

**功能**
- [ ] `GET /api/status` 返回 §2.1 全部字段，分页字段正确。
- [ ] 新增来源：正常创建返回 201；重复 feed_url 返回 400 且**不写库**。
- [ ] 启用/停用：`enabled` 正确翻转并持久化。
- [ ] 手动抓取：生成一条 `crawl_jobs` 记录，`raw_documents`/`content_items` 相应增长，失败时返回 500+error 且进程不崩。
- [ ] 任务翻页：上一页/下一页可用，首/末页按钮正确禁用，`总数 total` 准确。
- [ ] 前端四类操作（新增/抓取/启用停用/翻页）+ 搜索 + 状态筛选 + 主题切换，真实点击均有可见反馈。
- [ ] 浅色/深色两套主题均显示正常，移动端（≤980px）布局不破版。

**质量门禁（命令需贴执行结果）**
- [ ] `pytest`（含新增用例）全绿，覆盖率不低于现状（≥80%，见 `.coveragerc`）。
- [ ] `python -m ruff check .` 通过。
- [ ] `python -m mypy --config-file pyproject.toml src` 通过。
- [ ] `python -m core_data.scripts.audit_dod` 通过（确认未破坏 L0 静态约束）。
- [ ] `python -m core_data.scripts.smoke` 仍输出 `L0 PIPELINE: PASS ...`。

**不变量**
- [ ] 未新增越层 import；未对 `raw_documents` 做 update/delete；稳定事件/字段未变。

---

## 5. 自测要求（Self-Test）

### 5.1 单元测试（pytest，新增到 `tests/`）
使用临时 SQLite + 文件对象存储（参考现有 `tests/` 夹具），**必须覆盖**：
1. `test_status_shape`：响应含 `counts/sources/recent_content/recent_jobs/jobs_page/deltas/dedup`，字段类型正确。
2. `test_status_pagination`：插入 ≥20 条 `crawl_jobs`，校验 `offset/limit/total/has_prev/has_next`；`jobs_limit` 越界被 clamp 到 `[1,100]`。
3. `test_create_source_ok`：返回 201，库内新增一行，`SourceHealth` 同步创建。
4. `test_create_source_duplicate_feed`：同 feed_url 第二次返回 400，且库里仍只有 1 行。
5. `test_create_source_missing_name`：空 name 返回 400。
6. `test_toggle_source`：翻转后再次查询 `enabled` 取反；不存在的 id 返回 400。
7. `test_crawl_endpoint`：对带 fixture feed 的来源触发，断言新增 `crawl_jobs` 且 `stats` 字段齐全；对无 feed_url 来源触发返回 500。

> 建议把 handler 业务逻辑抽成纯函数（如 `_status/_create_source/_toggle_source/_run_crawl`），用 `SessionLocal` 直接调用做单测，避免起 HTTP server；另对路由用 1 个端到端用例（`http.client` 打本地端口）兜底。

### 5.2 手动冒烟（贴步骤与截图）
```bash
# 启动
python -m core_data.scripts.dashboard --host 127.0.0.1 --port 8088
# 浏览器打开 http://127.0.0.1:8088
```
逐项点击并记录：新增来源 → 列表+1；点新来源「抓取」→ 任务表+1、原始文档数增长；停用/启用 → 状态翻转；任务表翻到第 2 页再翻回；切换深色主题刷新后保持。

### 5.3 纯前端验证（无需后端）
直接用浏览器打开 `docs/dashboard-live-preview.html`（自带模拟后端），确认交互/样式与真实页面一致——作为前端回归基线。

---

## 6. 交付物（Deliverables）
1. 改造后的 `src/core_data/scripts/dashboard.py` + `dashboard.html`（真实接口、统一样式、删除任何 mock）。
2. `tests/` 下新增测试文件（§5.1）。
3. PR 描述：勾选 §4 清单 + 贴质量门禁命令输出 + 冒烟截图（浅/深各一张）。
4. 如 `deltas/dedup` 的实际计算口径与本文档有出入，在 PR 中说明。

---

## 7. 注意事项 / 风险
- **安全**：本期无鉴权，默认仅绑 `127.0.0.1`；切勿绑 `0.0.0.0` 暴露写接口。所有动态内容前端 `esc()`。
- **慢请求**：`/api/crawl` 同步阻塞，单次抓取可能数秒；前端已有「抓取中…」提示，后端需保证异常不导致连接挂死（try/except 包裹）。
- **CWD 依赖**：Alembic `script_location` 相对当前目录，迁移命令需在仓库根执行。
- **环境**：项目基于 Python 3.12（`.pyc` 为 cpython-312）；请在装好依赖的 3.12 环境运行测试与服务。
- **不要重复造领域逻辑**：新增来源用 `create_source`，抓取用 `crawl_source`，对象存储用 `build_object_store`，禁止在 dashboard 里手写 SQL 绕过仓储层。

---

## 附：现有数据模型速查（`core_data/db/models.py`）
- `Source(id, name, feed_url[unique], home_url, type, enabled, created_at, ...)`
- `CrawlJob(id, source_id, kind, started_at, finished_at, status, stats(JSON), error)`
- `ContentItem(id, canonical_url, url_hash[unique], title, lang, status, fetched_at, created_at, ...)`
- `RawDocument(id, source_id, crawl_job_id, url, fetch_method, fetched_at, raw_html_sha256, ...)` — **append-only**
- `OutboxEvent(id, topic, payload(JSON), idempotency_key[unique], created_at, published_at)`
