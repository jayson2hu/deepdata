# 真实公开内容预览：问题与实施计划

日期：2026-09-17。本文记录 L0 面向 CodePick 阅读场景的首轮真实数据改造。
原文只保存在本机测试目录，不随源码提交，也不替代来源站点；产品展示必须保留原文链接和来源署名。

## 已确认问题

- 现有 RSS 适配器没有把 feed 的 `published` 转成 `published_at`，导致来源时间丢失。
- 页面请求没有对 4xx/5xx 明确失败，错误页可能被当作正文。
- 采集入口缺少统一的每源条数、请求超时、请求间隔和最短正文约束。
- 当前 smoke 主要使用 fixture，缺少可复现的小批量真实来源 manifest、逐源失败和跨层定位报告。
- L1 只能看到部分来源字段，不能可靠区分公开 feed、抓取时间和处理方式。

## 本轮范围

1. 使用官方工程博客、产品发布说明等公开 RSS/Atom 来源，小批量采集；不绕过登录、付费墙或反爬限制。
2. manifest 为每个来源登记主页、feed、用途和展示策略；默认限制每源条数，并设置超时、间隔及最短正文。
3. 所有条目必须走 `crawl_source`、append-only raw、正文对象存储、规范化、去重/版本和 outbox。
4. 报告输出 sources、entries、content、failed、rejected、内容 ID、URL、版本、发布时间和抓取时间。来源级失败必须显式记录；零内容退出失败。
5. L0 查询向 L1 暴露 provenance：`source_kind=public_feed`、来源名称/主页/feed、原文 URL、抓取时间、发布时间、内容版本和 hash。
6. 测试数据固定写入调用者指定的新目录；本轮验收使用 `/tmp/codepick-real-preview-20260917`。

## 质量边界

- 仅接受 HTTP 成功响应和达到 `min_text_chars` 的正文；坏页保留 raw/error 证据。
- feed 发布时间无法解析时保持未知并记录，不用抓取时间冒充发布时间。
- 原文摘要、关键点等派生字段由 L1 明确标记的 `extractive-v3` 规则处理器产生，不声称模型翻译、评分或专家判断。
- 网络、来源格式和单页失败均进入报告。部分来源成功时可以保留结果，但报告必须显示失败；全部来源无内容时命令非零退出。

## 验收输出

```bash
deepdata/.venv/bin/python -m core_data.scripts.real_preview \
  --data-dir /tmp/codepick-real-preview-20260917/l0 \
  --manifest deploy/real-preview-sources.json \
  --report /tmp/codepick-real-preview-20260917/l0-report.json
```

输出的 `l0.db`、`objects/` 和报告只用于本机验收。L1 使用报告中的内容 ID 读取同一份 L0 快照。

## 2026-09-17 实际结果

本机最终报告为 `/tmp/codepick-real-preview-20260917/l0-report.json`，数据库为
`/tmp/codepick-real-preview-20260917/l0/l0.db`，对象目录为同级 `objects/`。

- 请求 3 个官方来源；GitHub Changelog、GitHub Engineering 成功，Google Developers Blog 因本机网络 `Network is unreachable` / TLS EOF 失败并写入报告。
- 两个成功来源各抓 5 篇，共 10 篇；页面失败 0、正文质量拒绝 0，内容 ID 为 1–10。
- 主体抽取改用 trafilatura，RSS 标题优先；HTMLParser 仅作回退。GitHub 的 Tags/Written by/Related posts 尾部在规范化前裁掉。
- 首次正文清洗升级使 10 篇都产生 v2；Related posts 精确裁剪又使 ID 7、8、10 产生 v3。最终共有 23 条 `content_versions` 和 23 条版本化 outbox，未直接覆盖 SQL。
- 最终正文不含 `Try GitHub Copilot app`、`Attend GitHub Universe` 或 `Related posts`，标题不再混入社交图标文字。

复抓现有测试库并验证版本路径：

```bash
.venv/bin/python -m core_data.scripts.real_preview --reuse \
  --data-dir /tmp/codepick-real-preview-20260917/l0 \
  --manifest deploy/real-preview-sources.json \
  --report /tmp/codepick-real-preview-20260917/l0-report.json
```

本机报告和原文不提交仓库。Google 来源失败是本次环境证据，不应改写为成功；下次联网验收可用同一 manifest 重试。



仓库级最终检查为 60 项测试通过，覆盖率 86.36%；包含 Playwright fixture 和只读运营
看板浏览器检查。Ruff、mypy strict（45 个源码文件）、pipeline smoke 和架构 audit
DoD 均通过。独立 loopback Compose 的 PostgreSQL、Redis、MinIO external DoD 与
quick soak 也通过：`iterations=1`、`new_raw_documents=2`、
`new_content_items=1`、`errors=[]`、`pass=true`。报告为
`/tmp/codepick-l0-real-external-dod.json`，测试容器、网络和卷已清理。


## 最终同源重放证据

在最终数据上再次运行相同 `--reuse` 命令，独立报告为
`/tmp/codepick-real-preview-20260917/l0-replay-report.json`。本次公开来源快照未发生
变化：重放前后均为 10 个 content item、23 个 content version 和 23 个 outbox
event；`new_content_items=0`、`new_content_versions=0`、
`new_outbox_events=0`，所有内容 ID 的 current_version 和 content_hash 保持不变。
Google Developers Blog 的网络失败仍在报告中显式保留。若公开上游未来真实更新，
相同命令应正常产生新内容版本，不能把“外部内容固定”作为幂等前提。
