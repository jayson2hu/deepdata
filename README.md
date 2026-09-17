# CodePick L0 数据底座

[2026-09-12 当前验证与剩余工作](docs/2026-09-12-continuation.md) · [平台项目进度](../codepick-docs/PROJECT_STATUS.md)

[异地开发指南](DEVELOPMENT.md) · [平台总文档与关联仓库](https://github.com/jayson2hu/codepick-docs)

L0 负责采集内容、不可变保存原始层、派生规范层、去重保留变体，并通过事务性 outbox 发出版本化 `content.ingested`。同 URL 正文变化会创建新的 `content_versions` 行和新的事件，不再被初始事件的幂等键吞掉。

## 本地运行

```bash
make up
make migrate
make smoke
make integration-smoke
```

没有 Docker/PG 时，默认 `DATABASE_URL=sqlite:///./.runtime/codepick_l0.db` 和文件对象存储也可以运行：

```bash
python -m core_data.scripts.smoke
```

成功输出：

```text
L0 PIPELINE: PASS ...
```

## 外部 DoD 验证

Docker Desktop/Linux engine 可用后，使用真实 PostgreSQL+pgvector、Redis、MinIO 跑最终验收：

```bash
make up
set DATABASE_URL=postgresql+psycopg://codepick:dev@127.0.0.1:55432/codepick
set REDIS_URL=redis://127.0.0.1:56379/0
set OBJECT_STORE_BACKEND=s3
set S3_ENDPOINT=http://127.0.0.1:59000
set S3_ACCESS_KEY=minio
set S3_SECRET_KEY=minio123
set S3_BUCKET=codepick-raw
make migrate
make external-dod
```

`make external-dod` 会执行：

- PostgreSQL、Redis、S3 对象存储 round trip 检查。
- L0 pipeline external smoke。
- Redis relay 幂等验证，确认同一个 `idempotency_key` 不会重复入队。
- 默认 24 小时 soak，并生成 `.runtime/external-dod-soak-report.json`。

快速预检可先运行：

```bash
python -m core_data.scripts.external_dod --skip-soak
python -m core_data.scripts.external_dod --soak-hours 0 --interval-sec 0 --report .runtime/external-dod-soak-quick.json
```

最终 DoD 的 soak 报告必须满足 `pass=true`、`new_raw_documents>=1`、`new_content_items>=1`、`errors=[]`。

## 关键契约

稳定事件：

```json
{
  "topic": "content.ingested",
  "payload": {
    "schema_version": 1,
    "content_id": 1,
    "content_version": 2,
    "content_hash": "...",
    "lang": "en"
  },
  "idempotency_key": "content.ingested:1:v2"
}
```

初始版本使用 `v1`，正文更新依次使用 `v2`、`v3`。相同版本重复写入仍由
outbox 唯一键幂等。

稳定查询：

- `list_contents(session, status, since, limit, cursor)`
- `get_content(session, object_store, content_id)`

稳定字段：

- `id`
- `current_version`
- `content_hash`
- `canonical_url`
- `title`
- `clean_text`
- `lang`
- `source`
- `published_at`
- `status`

## 表归属

L0 拥有：

- `sources`
- `source_health`
- `crawl_jobs`
- `raw_documents`
- `content_items`
- `content_versions`

实现还包含事务性 outbox 表 `outbox_events`。`raw_documents` 只通过 `RawStore.append()` 写入，仓储层没有 update/delete 方法。

## 验证

```bash
pytest
python -m ruff check .
python -m mypy --config-file pyproject.toml src
python -m pytest tests/integration/test_playwright_fetcher.py
python -m core_data.scripts.external_dod --skip-soak
python -m core_data.scripts.soak --hours 24 --interval-sec 300 --seed-fixture
python -m core_data.scripts.audit_dod
```

当前 fixtures 覆盖：RSS → raw_documents → HTML 对象存储 →正文提取 → content_items(WAIT_FILTER) → outbox → L1 查询契约。

## 小批量真实公开内容预览

内置 manifest 只登记官方公开 feed，并限制每源 5 篇、20 秒超时、0.5 秒页面间隔和最短正文。原文与数据库只写入调用者指定的本机目录：

```bash
.venv/bin/python -m core_data.scripts.real_preview \
  --data-dir /tmp/codepick-real-preview-20260917/l0 \
  --manifest deploy/real-preview-sources.json \
  --report /tmp/codepick-real-preview-20260917/l0-report.json
```

抽取规则升级后，可显式增加 `--reuse` 在同一数据库中重新抓取；正文变化必须经过去重、`content_versions` 和版本化 outbox，不能直接改 SQL。报告保留来源级失败和页面错误，零内容时命令返回失败。设计、权限边界和 2026-09-17 实测见 [真实公开内容预览](docs/2026-09-17-real-public-preview.md)。
