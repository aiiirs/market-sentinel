# MarketSentinel

[English](README.md) | [简体中文](README.zh-CN.md)

MarketSentinel 用于在 A 股交易时段监控指定场内 ETF 的 IOPV 溢价率。程序通过 AKShare 获取 ETF 实时行情；当溢价满足你设定的阈值时，向飞书（Lark）自定义机器人 Webhook 发送提醒。

> **免责声明**
> 本项目仅用于信息监控和技术实验，不构成投资建议。公开行情数据可能延迟、缺失、不可用或错误。请勿将本项目用于自动交易。

## 脚本会做什么

每一轮监控会按以下流程执行：

1. 判断当前是否处于上交所 A 股连续交易时段（北京时间 09:30–11:30、13:00–15:00）且为交易日。
2. 通过 AKShare / 东方财富获取你配置的 ETF 行情。
3. 将上游字段“基金折价率”转换为本项目使用的 IOPV 溢价率：正数表示溢价，负数表示折价。
4. 当某只 ETF 满足 `溢价率 <= 阈值` 时，发送低溢价提醒。
5. 将已提醒时间持久化到本地，避免同一 ETF 在冷却期内重复提醒。
6. 按单独设置的时间间隔发送分组溢价汇总。
7. 记录重试与失败；行情源连续失败达到设定次数后，尝试发送健康告警。

非 A 股交易时段，程序会保持运行，但不会请求行情或发送提醒。

## 消息类型

| 类型 | 触发时机 | 发送位置 |
|---|---|---|
| 低溢价提醒 | ETF 的 IOPV 溢价率小于或等于阈值，且不在冷却期内 | 主飞书 Webhook |
| 溢价汇总 | 每隔 `summary_interval_seconds` 秒，在有效交易时段发送；设为 `0` 可关闭 | 主飞书 Webhook |
| 健康告警 | 行情源连续失败达到 `failure_alert_after_rounds` 次，或消息发送失败 | 健康告警 Webhook；未设置时用主 Webhook |

一个分组只有一只有效 ETF 时，汇总显示单一溢价率；有多只 ETF 时，显示最低至最高溢价范围。汇总不展示价格、IOPV 或单只 ETF 代码。

## 运行环境

- Python 3.11 或更高版本。
- 一个飞书/Lark 自定义机器人 Webhook。
- 可访问 AKShare 上游行情和飞书/Lark 的网络。
- macOS 不是必需；仅自启动模板使用 macOS `launchd`。

## 快速开始

```bash
git clone https://github.com/aiiirs/market-sentinel.git
cd market-sentinel
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml
cp .env.example .env
```

然后按下文修改两个本地文件。这两个文件已被 Git 忽略，必须只保存在本机。

只执行一轮监控（不进入常驻模式）：

```bash
./run_market_sentinel.sh --once
```

持续运行：

```bash
./run_market_sentinel.sh
```

前台运行时使用 `Ctrl+C` 停止。

## 首次配置：必须修改什么

### 1. 创建飞书/Lark 自定义机器人 Webhook

在目标群聊中创建“自定义机器人（Incoming Webhook）”，复制其 Webhook 地址。不要把该地址写入源码、`config.toml`、截图、Issue 或 Git 提交。

### 2. 在 `.env` 中填入 Webhook

只在本机编辑 `.env`：

```bash
MARKET_SENTINEL_FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/替换为主通知地址
MARKET_SENTINEL_HEALTH_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/替换为健康告警地址
```

`MARKET_SENTINEL_FEISHU_WEBHOOK` 必填。`MARKET_SENTINEL_HEALTH_WEBHOOK` 可选但推荐使用不同的机器人或群聊：主 Webhook 本身失效时，不能可靠地报告自己的故障。

建议限制文件权限：

```bash
chmod 600 .env config.toml
```

### 3. 在 `config.toml` 中定义 ETF 与阈值

示例 ETF 只是占位内容。请改成你需要监控的 ETF 和阈值。

```toml
[monitor]
summary_groups = ["美股指数 ETF", "日本 ETF"]

[etfs."513500"]
name = "示例 ETF"
threshold = 1.0
# 当 IOPV 溢价率 <= 1.00% 时提醒。
group = "美股指数 ETF"

[etfs."513800"]
name = "另一只示例 ETF"
threshold = -2.0
# 负数阈值表示仅在折价达到 2% 或更多时提醒。
group = "日本 ETF"
```

`threshold` 使用百分比，不是小数比例：`1.0` 表示 1%，`0.5` 表示 0.5%，`-2.0` 表示 -2%。

## 完整配置说明

### `[monitor]`

| 字段 | 默认值 | 作用 |
|---|---:|---|
| `poll_seconds` | `300` | 有效交易时段内，两轮行情查询之间的秒数。 |
| `cooldown_seconds` | `1800` | 同一只 ETF 两次低溢价提醒之间的最短秒数。 |
| `summary_interval_seconds` | `1800` | 定时汇总的发送间隔（秒）；设为 `0` 可关闭汇总。 |
| `summary_groups` | `[...]` | 汇总卡片中展示的分组名称及顺序。其他分组仍可触发告警，但不会显示在定时汇总中。 |
| `health_cooldown_seconds` | `3600` | 同类健康告警的最短发送间隔（秒）。 |
| `failure_alert_after_rounds` | `3` | 全量行情连续失败达到该次数后，尝试发送健康告警。 |
| `random_delay_min_seconds` | `1` | 行情请求前随机等待的最小秒数。 |
| `random_delay_max_seconds` | `5` | 行情请求前随机等待的最大秒数。 |
| `max_retries` | `3` | 行情请求或 Webhook 请求失败时的最大尝试次数。 |
| `retry_delay_seconds` | `2` | 重试之间的基础等待秒数。 |
| `request_timeout_seconds` | `15` | 单次 HTTP 请求超时时间（秒）。 |
| `state_file` | `data/state.json` | 保存提醒冷却和汇总发送时间的本地 JSON 文件；不要提交或删除。 |
| `log_file` | `logs/market_sentinel.log` | 本地日志文件路径；不要提交日志。 |

### `[calendar]`

| 字段 | 默认值 | 作用 |
|---|---|---|
| `exchange` | `XSHG` | 用于判断 A 股交易日的交易所日历。 |

### `[feishu]`

| 字段 | 作用 |
|---|---|
| `webhook_env` | 保存主通知 Webhook 地址的必填环境变量名称。 |
| `health_webhook_env` | 保存健康告警 Webhook 地址的可选环境变量名称。留空时健康告警改用主 Webhook。 |

### `[etfs."<六位代码>"]`

每只需要监控的 ETF 建立一个配置块。

| 字段 | 作用 |
|---|---|
| `name` | 通知卡片中显示的名称。 |
| `threshold` | 百分比阈值。只有 `溢价率 <= threshold` 才会提醒。 |
| `group` | 逻辑分组名称。加入 `summary_groups` 后才会出现在定时汇总中。 |

## macOS 自动启动

仓库提供 `launchd/com.marketsentinel.monitor.plist.example`。

1. 将文件内所有 `__PROJECT_DIR__` 替换为本地项目的绝对路径。
2. 保存为 `~/Library/LaunchAgents/com.marketsentinel.monitor.plist`。
3. 加载并立即启动：

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.marketsentinel.monitor.plist
launchctl kickstart -k "gui/$(id -u)/com.marketsentinel.monitor"
```

查看状态：

```bash
launchctl print "gui/$(id -u)/com.marketsentinel.monitor"
```

停止并卸载：

```bash
launchctl bootout "gui/$(id -u)/com.marketsentinel.monitor"
```

## 日志与常见问题

| 现象 | 检查方式 |
|---|---|
| 没有提醒 | 确认当前是 A 股交易日且处于北京时间 09:30–11:30 或 13:00–15:00；检查阈值和冷却期。 |
| 配置报错 | 确认 `.env` 存在、必填 Webhook 变量不为空、`config.toml` 是合法 TOML。 |
| 行情请求失败 | 检查网络和日志；AKShare/东方财富上游接口可能超时或发生变更。 |
| Webhook 发送失败 | 确认机器人未被删除且地址仍有效；如 URL 泄露，立即轮换机器人。 |
| 重复提醒 | 不要删除 `state_file`，它保存跨重启的冷却与汇总状态。 |

## 开发与测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## 安全

Webhook 地址属于敏感信息。发布配置或报告安全问题前，请阅读 [SECURITY.md](SECURITY.md)。

## 数据来源

本项目使用 [AKShare](https://github.com/akfamily/akshare)，因此依赖公开上游行情数据。请自行核对上游条款及数据是否适合你的用途。

## 许可证

MIT，见 [LICENSE](LICENSE)。
