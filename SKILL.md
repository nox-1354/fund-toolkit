---
name: fund-toolkit
description: 当任务需要获取基金数据时使用——搜索基金、净值查询、评分分析、投资建议、定投回测、可视化报告等。依赖 Node.js 服务（公司列表/净值排行/主题榜单）和 akshare（评分/定投/相关性/可视化）。
origin: custom
version: 1.3.0
---

# Fund Toolkit - 基金全栈数据工具包 V1.3

## 何时激活

用户提到以下关键词时加载本 skill：

- 基金、净值、基金经理、基金公司、持仓
- 基金评分、基金对比、基金排名
- 定投、定投回测、定投收益
- 投资建议、C1、C2、C3、C4、C5、风险等级
- 基金报告、基金可视化、基金分析
- 基金搜索、基金筛选、基金主题

## 使用方式

```python
from fund_toolkit import FundToolkit

tk = FundToolkit()
```

## 核心功能

### 基金搜索（仅 requests）

```python
# 搜索基金
results = tk.search("易方达蓝筹")

# 获取基本信息
info = tk.get_fund("110011")

# 获取净值
nav = tk.get_net_value("110011")

# 获取持仓
holdings = tk.get_holdings("110011")
```

### 基金评分（需要 akshare）

```python
score = tk.get_score("110011")
# 返回: {total, grade, scores: {收益能力, 风险控制, 性价比, 稳定性}}
```

### 定投回测（需要 akshare）

```python
result = tk.drip("110011", amount=1000, frequency="monthly")
# 返回: {total_cost, final_value, total_return, annual_return}
```

### 投资建议

```python
# C1=保守 C2=稳健 C3=平衡 C4=积极 C5=进取
advice = tk.suggest("C3", amount=10000)
```

### 可视化报告（需要 akshare）

```python
tk.generate_report("110011", output_path="./report.html")
tk.generate_compare_report(["110011", "519069"], output_path="./compare.html")
```

## 依赖说明

| 功能 | 依赖 |
|------|------|
| 搜索/净值/持仓 | 仅 requests |
| 公司列表/净值排行/主题 | Node.js 服务 |
| 评分/定投/相关性/可视化 | akshare |

## 代码位置

所有代码在 `fund_toolkit/` 目录：

- `core.py` — 核心功能（11层）
- `advisor.py` — 投资建议
- `vis.py` — 可视化
