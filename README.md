<p align="center">
  <h1 align="center">Fund Toolkit</h1>
</p>

<p align="center">
  基金全栈数据工具包 - 搜索基金、净值查询、评分分析、定投回测、HTML可视化报告
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="License"></a>
  <a href="https://github.com/nox-1354/fund-toolkit"><img src="https://img.shields.io/badge/Status-Active-brightgreen" alt="Status"></a>
  <a href="https://github.com/nox-1354/fund-toolkit"><img src="https://img.shields.io/github/stars/nox-1354/fund-toolkit?style=social" alt="Stars"></a>
</p>

> 📚 **请仔细阅读本文档后再使用**

---

## 功能概览

<div align="center">

| 模块 | 功能 | 依赖 |
|------|------|------|
| **搜索** | 基金代码/名称搜索 | 仅 requests |
| **净值** | 基金净值查询 | 仅 requests |
| **持仓** | 基金持仓分析 | 仅 requests |
| **公司** | 基金公司列表 | Node.js 服务 |
| **净值排行** | 全市场净值排名 | Node.js 服务 |
| **主题榜单** | 基金主题榜单 | Node.js 服务 |
| **评分** | 5维度综合评分 | akshare |
| **定投** | 定投收益回测 | akshare |
| **相关性** | 基金相关性分析 | akshare |
| **可视化** | HTML 交互式报告 | akshare |
| **投资建议** | C1-C5 风险匹配 | 仅 requests |

</div>

---

## 快速开始

### 快速安装入口

```
pip install git+https://github.com/nox-1354/fund-toolkit.git
```

### 1. 安装

```bash
# 基础安装（搜索 + 净值 + 持仓）
pip install requests pandas numpy beautifulsoup4

# 完整安装（体验完整功能需 akshare）
pip install akshare
```

### 2. 启动 Node.js 服务（可选）

公司列表、净值排行、主题榜单需要 Node.js 服务：

```bash
git clone https://github.com/kouchao/TiantianFundApi
cd TiantianFundApi
npm install
npm start  # 默认 localhost:3000
```

### 3. 基础用法

```python
from fund_toolkit import FundToolkit

tk = FundToolkit()

# 搜索基金
results = tk.search("易方达蓝筹")
for r in results[:3]:
    print(f"{r['CODE']}: {r['NAME']}")

# 获取基金基本信息
info = tk.get_fund("110011")
print(f"名称: {info['NAME']}")
print(f"类型: {info['CATEGORYDESC']}")

# 获取基金评分（需要 akshare）
score = tk.get_score("110011")
print(f"综合评分: {score['total']}/5.0")
print(f"评级: {score['grade']}")

# 定投回测（需要 akshare）
result = tk.drip("110011", amount=1000, frequency="monthly")
print(f"收益率: {result['total_return']:.2f}%")

# 投资建议（C1=保守 ~ C5=进取）
advice = tk.suggest("C3", amount=10000)
print(advice)

# 生成可视化报告（需要 akshare）
tk.generate_report("110011", output_path="./fund_report.html")
```

---

## API 参考

所有功能通过 `FundToolkit` 类统一调用：

<div align="center">

| 方法 | 说明 | 依赖 |
|------|------|------|
| `search(keyword)` | 搜索基金 | 仅 requests |
| `get_fund(code)` | 基金基本信息 | 仅 requests |
| `get_name(code)` | 基金名称 | 仅 requests |
| `get_type(code)` | 基金类型 | 仅 requests |
| `get_manager(code)` | 基金经理 | 仅 requests |
| `get_company(code)` | 基金公司 | 仅 requests |
| `get_net_value(code)` | 最新净值 | 仅 requests |
| `get_holdings(code)` | 基金持仓 | 仅 requests |
| `get_companies()` | 基金公司列表 | Node.js |
| `get_net_list(top_n)` | 净值排行 | Node.js |
| `get_themes()` | 主题榜单 | Node.js |
| `get_score(code)` | 基金评分 | akshare |
| `drip(code, **kwargs)` | 定投回测 | akshare |
| `get_correlation(codes)` | 相关性分析 | akshare |
| `suggest(risk_level, amount)` | 投资建议 | 仅 requests |
| `generate_report(code, output_path)` | HTML 报告 | akshare |
| `generate_compare_report(codes, output_path)` | 对比报告 | akshare |
| `test_connection(verbose)` | 测试数据源 | 仅 requests |
| `clear_cache(pattern)` | 清除缓存 | 仅 requests |
| `get_version()` | 版本号 | 仅 requests |

</div>

### 定投参数详解

```python
tk.drip(
    code="110011",           # 基金代码
    amount=1000,             # 每期金额
    start_date="2020-01-01", # 开始日期（可选）
    end_date="2026-01-01",   # 结束日期（可选）
    frequency="monthly",     # monthly / weekly / biweekly / quarterly
    day_of_month=1,          # 每月几号（月度/季度）
    day_of_week=1,           # 周几（每周/双周，0=周一）
    fee_rate=0.0015          # 申购费率
)
```

### 投资建议风险等级

<div align="center">

| 等级 | 类型 | 说明 | 股债配置建议 |
|------|------|------|-------------|
| C1 | 保守型 | 追求本金安全，可接受极低收益 | 股票0% / 债券80% / 货币20% |
| C2 | 稳健型 | 追求稳定收益，可接受小幅波动 | 股票10% / 债券70% / 货币20% |
| C3 | 平衡型 | 追求资产增值，接受中等波动 | 股票30% / 债券55% / 货币15% |
| C4 | 积极型 | 追求较高收益，接受较大波动 | 股票50% / 债券40% / 货币10% |
| C5 | 进取型 | 追求高收益，接受大幅波动 | 股票70% / 债券25% / 货币5% |

</div>

---

## 使用场景示例

### 场景一：新基金快速调研

```python
from fund_toolkit import FundToolkit
tk = FundToolkit()

code = "110011"

# 1. 基本信息
info = tk.get_fund(code)
print(f"{info['NAME']} ({code})")
print(f"类型: {info['CATEGORYDESC']}")

# 2. 净值
nav = tk.get_net_value(code)
print(f"净值: {nav['DWJZ']} ({nav['FSRQ']})")

# 3. 评分（需要 akshare）
score = tk.get_score(code)
print(f"评分: {score['total']}/5.0 - {score['grade']}")

# 4. 持仓
holdings = tk.get_holdings(code)
print(holdings.head(10))
```

### 场景二：定投策略对比

```python
# 对比不同金额的定投效果
result = tk.compare_drip(
    code="110011",
    amounts=[500, 1000, 2000],
    frequency="monthly"
)
print(result)
```

### 场景三：生成投资建议报告

```python
# C3 平衡型，投资 10 万元
advice = tk.suggest("C3", amount=100000)
print(advice)

# 生成可视化报告（需要 akshare）
tk.generate_report("110011", output_path="./report.html")
```

### 场景四：基金对比

```python
# 对比多只基金
compare = tk.compare(["110011", "519069", "000001"])
print(compare)

# 对比评分（需要 akshare）
score_compare = tk.compare_scores(["110011", "519069", "000001"])
print(score_compare)

# 生成对比报告（需要 akshare）
tk.generate_compare_report(
    ["110011", "519069", "000001"],
    output_path="./compare.html"
)
```

---

## 依赖说明

### 基础依赖（必须安装）

<div align="center">

| 包 | 版本 | 用途 |
|---|------|------|
| `requests` | >=2.28.0 | HTTP 请求 |
| `pandas` | >=1.5.0 | 数据处理 |
| `numpy` | >=1.24.0 | 数值计算 |
| `beautifulsoup4` | >=4.11.0 | HTML 解析（持仓分析） |

</div>

### 可选依赖

<div align="center">

| 包 | 用途 | 影响的功能 |
|---|------|-----------|
| `akshare` | 基金历史净值 | 评分、定投、相关性、可视化 |

</div>

### Node.js 服务

部分功能需要启动 Node.js 服务（[天天基金 API](https://github.com/kouchao/TiantianFundApi)）：

<div align="center">

| 功能 | 无服务时 |
|------|----------|
| 基金公司列表 | 返回空列表 |
| 全市场净值排行 | 返回空列表 |
| 基金主题榜单 | 返回空列表 |
| 基金筛选 | 返回空列表 |

</div>

---

## 项目结构

```
fund-toolkit/
├── fund_toolkit/
│   ├── __init__.py      # 包入口
│   ├── core.py           # 核心功能（11层架构）
│   ├── advisor.py        # 投资建议引擎（C1-C5）
│   └── vis.py            # 可视化扩展（HTML报告）
├── examples/             # 使用示例
│   ├── basic_usage.py
│   ├── investment_advice.py
│   ├── fund_score.py
│   └── drip_backtest.py
├── pyproject.toml        # pip 安装配置
├── requirements.txt      # 依赖列表
├── README.md             # 本文档
├── SKILL.md & SKILL_SIMPLE.md                 # Claude Skill 入口（调试中，暂不可用）
└── LICENSE               # MIT 许可证
```

---

## 致谢

本项目受以下开源项目/资料启发：

- **[a-stock-data](https://github.com/simonlin1212/a-stock-data)** — 作者 simonlin1212 的 A 股全栈数据工具包，本项目的架构设计、Skill 格式、工程化思路均受其启发，在此深表感谢 🙏

- **[TiantianFundApi](https://github.com/kouchao/TiantianFundApi)** — 天天基金 Node.js API 服务，为本项目提供公司列表、净值排行、主题榜单等数据支持

- **天天基金网 (fund.eastmoney.com)** — 提供基金搜索、净值、持仓等基础数据接口

---

## License

MIT License

Copyright (c) 2026 NOX-1354
