# MarketSentinel

[English](README.md) | [简体中文](README.zh-CN.md)

MarketSentinel 用于在 A 股交易时段监控指定场内 ETF 的 IOPV 溢价率；当满足设定阈值时，通过飞书（Lark）自定义机器人 Webhook 发送提醒。它还支持定时分组汇总与健康告警。

> **免责声明**
> 本项目仅用于信息监控和技术实验，不构成投资建议。行情数据可能存在延迟、缺失或错误。

## 功能

- 可配置 ETF 代码、分组、溢价阈值、轮询间隔和提醒冷却时间。
- 基于 AKShare ETF 实时行情计算 IOPV 溢价率。
- 通过飞书/Lark 自定义机器人 Webhook 发送交互式卡片提醒。
- 定时发送分组溢价汇总，支持独立的健康告警 Webhook。
- 判断 A 股交易时段和交易日历。
- 本地持久化冷却状态、日志、重试机制和单元测试。

## 快速开始

```bash
git clone <你的仓库地址>
cd MarketSentinel
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml
cp .env.example .env
```

在 `config.toml` 中填写要监控的 ETF 和阈值；在本机 `.env` 中填写飞书 Webhook 地址。不要提交这两个文件。

执行一次轮询：

```bash
./run_market_sentinel.sh --once
```

持续运行：

```bash
./run_market_sentinel.sh
```

## 配置

`config.toml` 控制监控行为。Webhook 地址由 `[feishu]` 中配置的环境变量读取；`.env.example` 使用以下变量：

```bash
MARKET_SENTINEL_FEISHU_WEBHOOK=
MARKET_SENTINEL_HEALTH_WEBHOOK=
```

建议使用独立的健康告警 Webhook：主 Webhook 自身失效时，无法可靠地报告自己的故障。

## macOS 自动启动

参考 `launchd/com.marketsentinel.monitor.plist.example`。将所有 `__PROJECT_DIR__` 占位符替换为本地克隆目录的绝对路径，再使用 `launchctl` 加载。

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
