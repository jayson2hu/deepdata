# L0 只读内容运营看板

日期：2026-09-17。看板沿用项目现有 Python HTTP 服务和单文件页面，没有新增前端框架。

## 查看本机真实数据

从 deepdata 仓库启动，只绑定本机：

```bash
DATABASE_URL=sqlite:////tmp/codepick-real-preview-20260917/l0/l0.db \
.venv/bin/python -m core_data.scripts.dashboard \
  --host 127.0.0.1 --port 18000 --read-only
```

访问 http://127.0.0.1:18000/ 。远程访问时给现有 SSH 隧道增加 `-L 18000:127.0.0.1:18000`；不要把这个开发看板公开到公网。

`--read-only` 必须使用已存在且已迁移的 L0 数据库。启动检查文件和所需表，不调用 `create_all`，缺库/缺表明确报错。所有 POST 在读取请求体和分派业务函数前返回 403；页面标注只读并隐藏来源新增、启停与抓取按钮。它不会启动采集或 outbox relay。

去掉 `--read-only` 保留原来的本地开发管理模式，包括来源创建和手动采集。管理模式没有生产身份认证，只能用于明确的本地开发数据库。

## 运营视图与数据口径

- 来源健康：最近尝试/成功、连续失败次数、真实错误说明；健康未知不当作正常。
- 内容：当前版本、来源、采集时间与原始发布时间分别展示；无发布时间显示未知。
- 关注区：最早 5 条待投递事件和最近 5 条失败任务；失败数明确为历史任务数。
- 投递：没有事件时显示“尚无投递事件”，API 返回 `delivery_rate: null`。已发布只表示 L0 outbox 发送，不表示下游确认。
- 页面仅展示最近 12 条内容与最多 50 个来源，并注明筛选/展示范围。
- 调度心跳来自本机文件，明确标注它不能证明当前数据库正在采集。
- 刷新失败保留最近一次成功结果，醒目标记数据可能过期，支持再次刷新。
- 仅 HTTP(S) 地址可成为外链；其他地址显示普通文本，外链使用 `noopener noreferrer`。
- 桌面与窄屏采用适合运营检查的布局；移动端表格转为纵向记录。

## 本次定向验收

```bash
.venv/bin/python -m pytest --no-cov \
  tests/unit/test_dashboard_readonly.py tests/unit/test_dashboard_multisource.py \
  -m "not integration" -q
.venv/bin/python -m ruff check \
  src/core_data/scripts/dashboard.py tests/unit/test_dashboard_readonly.py
.venv/bin/python -m mypy --config-file pyproject.toml src/core_data/scripts/dashboard.py
```

结果：13 项后端检查通过（其中 3 项为原有多来源回归），Ruff 与 mypy 通过。覆盖 POST 拒绝、开发模式兼容、零分母、健康/版本/待投递、启动不创建文件/表、存储失败 503。

浏览器测试使用真实 loopback HTTP 服务和独立 SQLite 测试数据，没有 API mock：

```bash
.venv/bin/python -m pytest --no-cov tests/unit/test_dashboard_readonly.py \
  -m integration -q
```

结果：390px 手机与 1280px 桌面共 2 项通过；验证只读按钮隐藏、安全链接、无页面横向溢出和服务错误后的旧数据/过期提示。可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定已有 Chromium；本机复用了 /tmp 下的 Chrome for Testing 和浏览器动态库。此定向检查关闭覆盖率收集以免与并行全仓库验收互相覆盖，未降低全仓库覆盖率门槛。

## 中文截图字体（已解决）

最初服务器 headless 浏览器缺少中文字形，截图显示方框。本轮通过 Ubuntu 的
`fonts-noto-cjk` 包解决；只下载并解压到临时目录，没有安装系统包或改用户配置。

本机复用时，为 Playwright 进程设置
`FONTCONFIG_FILE=/tmp/codepick-fonts.2vIbAN/fonts.conf`。
Chromium 路径为
`/tmp/codepick-chrome-headless-shell-complete/chrome-headless-shell-linux64/chrome-headless-shell`，
动态库目录为 `/tmp/codepick-playwright-libs/usr/lib/x86_64-linux-gnu`。

带字体复验仍为 2 项通过；已目视确认手机截图中文正常、没有缺字方框。配置可由
Reader Web 的 Playwright 进程继承同一个 `FONTCONFIG_FILE`。字体缓存只生成在
`/tmp/codepick-fonts.2vIbAN/cache`；这不是远程访问者浏览器的必需配置。

临时目录被清理后的重建步骤：

1. 用 `mktemp -d /tmp/codepick-fonts.XXXXXX` 创建新目录，在该目录执行
   `apt download fonts-noto-cjk`。
2. 用 `dpkg-deb -x <实际下载的deb文件> <临时目录>/extracted` 解压，不使用系统安装。
3. 在临时目录创建 `fonts.conf`，将下面的路径替换为新目录：

```xml
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir>/usr/share/fonts</dir>
  <dir>/tmp/codepick-fonts.2vIbAN/extracted/usr/share/fonts/opentype/noto</dir>
  <cachedir>/tmp/codepick-fonts.2vIbAN/cache</cachedir>
  <alias><family>sans-serif</family><prefer><family>Noto Sans CJK SC</family><family>DejaVu Sans</family></prefer></alias>
  <alias><family>system-ui</family><prefer><family>Noto Sans CJK SC</family><family>DejaVu Sans</family></prefer></alias>
</fontconfig>
```

本机下载版本为 `1:20230817+repack1-3`，包大小 61.2 MB。Chromium 会在指定目录
创建缓存，不需要系统的 `fc-cache` 命令。完整 L0 回归由整合步骤另行记录。
