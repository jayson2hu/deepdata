# L0 恢复开发与消息可靠性修复（2026-09-12）

## 当前结论

本仓库已恢复到 `D:\fayun\code\codepick\deepdata`，基线提交为 `ab0cd79`（2026-09-12，Publish CodePick L0 with portable development setup）。这是一次导入提交，Git 历史不能证明各功能此前逐阶段验收。本次在独立 Python 3.12.14 `.venv` 中重新安装开发依赖并验证本地运行能力。

L0 的采集、原始数据保存、规范化、去重、版本记录、查询契约和事务性 outbox 已有可运行实现。本次还修复了 Redis 发布器在入队失败后可能静默丢失事件的问题。真实 PostgreSQL、Redis、MinIO 联调与 24 小时无人值守验收仍不属于本次完成项。

## 重新核对的功能范围

| 范围 | 代码现状与证据 |
| --- | --- |
| 来源管理 | sources/source_health、OPML 导入、重复来源控制、到期调度均有实现和离线测试。 |
| 原始层 | RawStore 提供 append 接口；文件/S3 对象存储、HTML 引用、采集失败证据和媒体引用有实现。数据库权限层面的不可变性另需真实环境验证。 |
| 规范层 | 正文提取、URL/content hash/simhash、重复与变体保留、同 URL 版本变化、lineage/rebuild 有实现。 |
| 多源 | RSS、HTML 列表、GitHub Trending、百度/知乎/微博 JSON 热榜共 6 类适配器有实现；后 3 类本次仅验证通用 JSON fixture，未确认真实平台响应与授权。抖音、小红书另外 2 类仍明确抛出 NotImplementedError。 |
| 调度/界面 | scheduler_run 可执行单次/循环调度与心跳；本地 dashboard 的来源/状态接口有单测。Arq worker 仍只有 ping 骨架。 |
| 事件与查询 | 内容和 outbox 在同一 SQLAlchemy session 内写入；list_contents/get_content 提供 L1 稳定字段。默认 Redis 通道实际是名为 codepick:l0:events 的 List。 |

旧 `L0-SPRINT-STATUS.md` 中 `D:\vscodefile\deepdata`、无 Git 工作树及旧机器 Docker 可用性的叙述属于历史记录。它们不代表当前机器状态；本机未发现可用 Docker 命令。

## 本次修复

原 RedisStreamPublisher 先写 SET NX 幂等标记，再序列化并 RPUSH。若 JSON 序列化、RPUSH 或两次命令之间发生故障，幂等标记可能已经存在，下一次 relay 会跳过入队并把数据库 outbox 标成已发布。

现在发布器先检查 TTL、键冲突并序列化事件，然后执行同一段 Redis Lua：检查幂等标记 → RPUSH → 写有过期时间的接受标记。默认队列、键前缀、7 天有效期和事件 JSON 结构保持既有契约。Lua 不回滚已执行的命令，因此成功标记必须在入队之后；这保证 RPUSH 失败不会留下错误的成功标记。TTL 限定为 1 到 2147483647 的整数，避免无效过期参数在入队之后才触发错误。

新增 `fakeredis[lua]` 开发依赖，由真实 Lua 解释器执行生产脚本。回归覆盖：重复发布不重复入队；队列错误类型时 outbox 保持待发布、修复队列后可重试；Redis 执行成功但客户端丢失响应后重试不重复；无效 JSON、TTL 和冲突键不会留下成功标记。对未修复实现运行这些回归时为 9 失败/1 通过，其中错误队列和无效 JSON 的测试直接复现了错误成功标记；修复后全部通过。

可靠性边界：本次验证使用内存 Redis 模拟器及 Lua 解释器，尚未在真实 Redis 上运行新脚本。Redis 持久化、故障转移、集群键槽和超过幂等 TTL 的重试仍需部署验证。异常若发生在入队后但成功标记写入前，重试可能重复；消费者仍应按 idempotency_key 去重。已有实例中旧实现遗留的错误标记和历史丢失事件不会被本修复自动重建。

## 本次验证结果

| 检查 | 结果 |
| --- | --- |
| 原基线离线测试 | 36 passed，1 deselected；覆盖率 86.11%。 |
| 修复后完整离线测试 | 45 passed，1 deselected；覆盖率 86.25%，通过 80% 门槛；发布器覆盖率 100%。 |
| 发布器/outbox 定向回归 | 13 passed。 |
| Ruff | 通过。 |
| Mypy | 44 个源文件通过。 |
| pip check | 无依赖冲突。 |
| 离线 smoke | L0 PIPELINE: PASS sources=1 entries=1 raw=2 content=1 events=1 failed=0。 |
| 静态 DoD audit | 7 项通过；检查结构和字段，不代表外部基础设施验收。 |

排除的 1 项是 `tests/integration/test_playwright_fetcher.py`，需要 Playwright 对应 Chromium，当前缓存不可用；未把它计为通过或 pytest skip。没有运行真实平台抓取、外部服务验收、消息发送或 24 小时 soak。测试结果 XML 在本机 `.runtime/verification/pytest.xml`（运行产物，不提交）。

从本仓库目录复核：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -m 'not integration' -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy --config-file pyproject.toml src
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m core_data.scripts.audit_dod
```

本次 smoke 显式指定了 `.runtime/verification/smoke.db` 和 `.runtime/verification/smoke-objects`，并将 OBJECT_STORE_BACKEND 设为 file。配置存储目录的变量名是 OBJECT_STORE_PATH。当前 smoke 会删除它使用的 SQLite 数据库和对象目录，因此日常运行数据应与 smoke 验证目录隔离；本次没有使用已有业务数据目录。

## 后续优先事项

1. 在真实单节点 Redis 上验证新 Lua 的正常发布、重复、失败重试和客户端丢响应；随后恢复 PostgreSQL/MinIO 联调及原定长时间验收。
2. 落实 L0 到 L1 的消息消费和数据读取桥接。L0 事件中的 content_id 为整数；跨层消费端应明确归一化和去重规则。相关 L1 改进见同级 seek_data 仓库本次记录。
3. scheduler_run 的 --relay 当前只调用日志发布器并标记 outbox 已发布，不能用它完成真实跨层投递。真实 Redis 单批入口是 core_data.scripts.relay --once；生产调度与投递组合需继续完善。
4. 明确 TREND 的下游行为：该分支同样发送 content.ingested，但 status=TREND、lang=None、clean_text 为空。全文分析流程不能将此视为已完成正文采集。
5. 按真实响应校验各热榜平台适配器；落实有授权的数据来源，再开发抖音/小红书集成。为浏览器集成测试补齐可复用环境，CI 当前未安装 Chromium。
