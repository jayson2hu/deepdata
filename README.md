# CodePick L0 数据底座

[异地开发指南](DEVELOPMENT.md) · [平台总文档与关联仓库](https://github.com/jayson2hu/codepick-docs)

L0 负责采集内容、不可变保存原始层、派生规范层、去重保留变体，并通过事务性 outbox 发出 `content.ingested {content_id, lang}`。

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
{"topic":"content.ingested","payload":{"content_id":1,"lang":"en"}}
```

稳定查询：

- `list_contents(session, status, since, limit, cursor)`
- `get_content(session, object_store, content_id)`

稳定字段：

- `id`
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
