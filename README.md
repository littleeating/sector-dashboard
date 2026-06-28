# 同花顺导出股票筛选脚本

这个项目用于读取同花顺导出的 CSV/Excel 股票列表，按“近 X 个交易日涨幅超过 Y%”和“近 A 个交易日涨幅不超过 B%”筛选股票，并输出公司摘要结果表。成交量、换手率、量比等其他技术指标仍可通过 JSON 配置追加；不填配置即不关注这些指标。

## 运行方式

如果本机没有把 Python 加到 `PATH`，可以直接使用 Codex 内置 Python：

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' stock_filter.py --input data/input.template.xlsx --rise-days 20 --rise-threshold 30 --flat-days 5 --flat-threshold 10 --output output/selected.xlsx
```

如果还想叠加成交量、换手率、量比等技术指标，再加上 `--config`：

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' stock_filter.py --input data/input.template.xlsx --rise-days 20 --rise-threshold 30 --flat-days 5 --flat-threshold 10 --config config/rules.example.json --output output/selected.xlsx
```

## 输入文件

支持 `.xlsx`、`.xls`、`.csv`。

CSV 会依次尝试 `utf-8-sig`、`gbk`、`gb18030` 编码。

第一行必须是字段名。模板文件包含这些常见字段：

- `代码`
- `名称`
- `涨跌幅`
- `换手率`
- `量比`
- `市盈率`
- `总市值`
- `行业`
- `概念`
- `近20日涨幅`
- `近5日涨幅`
- `主营业务`
- `近1季度营收`
- `近1季度净利润`
- `近1季度净利润增速`
- `近2季度营收`
- `近2季度净利润`
- `近2季度净利润增速`
- `近3季度营收`
- `近3季度净利润`
- `近3季度净利润增速`
- `近4季度营收`
- `近4季度净利润`
- `近4季度净利润增速`

同花顺导出的百分号字段可以保留 `%`，例如 `3.5%`；带逗号的数字也可以读取，例如 `1,234.56`。

涨幅字段支持常见列名，例如：

- `近20日涨幅`
- `近20个交易日涨幅`
- `20日涨跌幅`

如果没有直接涨幅列，也可以提供 `最新价` 和 `20日前收盘价`，脚本会自动计算。

## 规则配置

规则文件使用 JSON，根节点可以包含 `rules`。如果运行时不传 `--config`，脚本只使用两个涨幅条件，不再关注成交量等其他技术指标。

分组规则：

- `all`：所有子条件都必须满足
- `any`：任意一个子条件满足即可

条件操作符：

- 数值：`>`, `>=`, `<`, `<=`, `==`, `!=`, `between`
- 文本：`contains`, `not_contains`, `in`, `not_in`
- 空值：`is_empty`, `not_empty`

如果配置引用了输入文件里不存在的列，脚本会直接停止，并提示缺失字段，避免误选。

## 输出文件

输出 Excel 只包含入选股票，并保留这些字段：

- `股票名称`
- `股票板块`
- `主营业务`
- 近 4 个季度的 `营收`
- 近 4 个季度的 `净利润`
- 近 4 个季度的 `净利润增速`
- `近X日涨幅`
- `近A日涨幅`
- `命中规则`
- `筛选时间`

如果输入文件里缺少某些输出字段，脚本会提示并把对应列留空。

## 后续扩展

第一版只筛选同花顺导出的现有字段，不计算 MACD、均线、KDJ 等历史 K 线指标。后续可以增加历史行情数据源，再把本地指标计算接入规则引擎。

## 板块动量看板

本项目新增一个独立的静态网页看板，用来统计行业板块和概念板块在近 `5/10/20/30/45/60` 个交易日的累计涨幅排名，每个周期默认展示前 `20` 名，并把重点板块的 60 日趋势画在同一张 SVG 图里。

看板会分别标注行业板块和概念板块的数据来源。每个周期标题都是可点击按钮，点击后，上方趋势图会切换为该周期全部入榜板块的增长曲线图。

离线生成样例网页：

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' sector_dashboard.py --sample --output output/sector_dashboard/index.html
```

实时数据模式需要安装 AKShare：

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pip install akshare
```

安装后生成实时网页：

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' sector_dashboard.py --output output/sector_dashboard/index.html
```

只做接口冒烟验证时，可以限制每类板块数量，避免首次验证请求过多：

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' sector_dashboard.py --output output/sector_dashboard/live-smoke.html --board-limit 1 --min-delay 0 --max-delay 0
```

默认安全访问策略：

- 默认 `--max-workers 1`，按顺序访问数据源。
- `--max-workers` 硬上限为 `2`，超过会直接报错。
- 每次外部请求之间随机等待 `--min-delay 1.2` 到 `--max-delay 2.5` 秒。
- 命中 `cache/sector_dashboard/` 缓存时不会重复请求同一板块。
- 遇到 403、429、验证码、登录页等疑似限流信号时会停止新增外部请求，并尽量使用缓存生成页面。
- `--board-limit` 默认为 `0`，表示全量；只建议手动验证时临时设置为 `1` 或 `2`。

建议通过 Windows 任务计划程序在交易日 `16:30` 后每天运行一次实时命令，输出文件会覆盖 `output/sector_dashboard/index.html`。第一次实时运行需要建立缓存，速度会比较慢；日常更新会优先使用缓存，压力小得多。

也可以先手动运行更新脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/update_sector_dashboard.ps1
```

确认实时模式可用后，再用管理员或当前用户权限注册每日任务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/register_sector_dashboard_task.ps1
```

注册后会创建名为 `SectorMomentumDashboardDailyUpdate` 的 Windows 任务计划，每天 `16:30` 运行 `scripts/update_sector_dashboard.ps1`。
