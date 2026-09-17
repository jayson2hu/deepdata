# L0 异地开发指南

本仓库属于 [CodePick 四层平台](https://github.com/jayson2hu/codepick-docs)。建议四个代码仓库保持同级目录，以便查阅关联实现；每个项目使用独立虚拟环境。

## 克隆与环境

需要 Git 和 Python 3.12 或更新版本。以下命令都从本仓库根目录执行。

```sh
git clone https://github.com/jayson2hu/deepdata.git
cd deepdata
python -m venv .venv
```

激活环境：Windows PowerShell 使用 `.venv\Scripts\Activate.ps1`；macOS/Linux 使用 `source .venv/bin/activate`。随后执行：

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m core_data.scripts.smoke
```

## 当前运行模式

默认可用 SQLite 和文件对象存储验证 L0。真实基础设施启动入口：`docker compose -f deploy/docker-compose.yml up -d`；浏览器抓取需要 `python -m playwright install chromium`。真实 PostgreSQL、Redis、MinIO 的联调步骤见 README 和 docs。

同 URL 正文变化会自动发出新的版本事件。可用
`python -m core_data.scripts.relay --once` 将待发布 outbox 写入 Redis；
事件幂等键包含 `content_id` 和 `content_version`。跨层 Redis/Arq 验收见
平台仓库 `scripts/verify_version_loop.py`。

Ubuntu 测试 Compose 仅绑定 localhost，并使用 PostgreSQL `55432`、Redis `56379`、MinIO API `59000`、MinIO Console `59001`，避免覆盖宿主机默认端口。

## 交接范围

提交包括当前源码、测试、迁移、配置示例与项目文档。依赖目录、构建产物、本地数据库、采集运行数据、日志和凭据不随仓库分发，需要在新环境重新安装或配置。

各层状态与验收证据见项目 README 和 docs；本文提供恢复开发的入口，不代表本次发布重新完成生产环境验收。

## 真实公开来源本机验收

真实内容预览使用 [官方来源 manifest](deploy/real-preview-sources.json) 和调用者指定的独立目录。首次运行及通过正常版本路径复抓的命令见 [2026-09-17 记录](docs/2026-09-17-real-public-preview.md)。不要提交生成的原文、对象文件、SQLite 数据库或报告；展示内容必须保留来源链接和署名策略。
