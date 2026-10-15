# 使用示例

本目录包含 `fund-toolkit` 的典型用法。

## 前提条件

**无需安装任何依赖**（Python 3.8+ 即可）。每个示例都自带路径引导，直接运行：

```bash
python examples/basic_usage.py
python examples/fund_score.py
python examples/drip_backtest.py
python examples/investment_advice.py
python examples/filter_and_correlate.py
```

如果你已经 `pip install .`，示例里的 `sys.path` 引导也不会产生副作用（先找到本地那份优先）。

## 示例列表

| 文件 | 功能 | 是否需要网络 |
|------|------|------|
| `basic_usage.py` | 搜索、基本信息、历史净值（复权）、评分、持仓 | 是 |
| `fund_score.py` | 多基金四维评分横向对比（覆盖 5 种基金类型） | 是 |
| `drip_backtest.py` | 定投回测：不同金额/频率，含 XIRR 年化与一次性投入基准 | 是 |
| `investment_advice.py` | C1-C5 投资建议，含 `max_risk` 档位收敛 | 是 |
| `filter_and_correlate.py` | 排行、筛选、相关性矩阵、相似基金 | 是 |

## 输出要点

- **复权口径**：收益、回撤、波动率、相关性都基于复权净值（累计净值差分法，含分红再投资）。
  分红日不会被算成暴跌。
- **年化为真实口径**：按实际日历跨度年化；定投用 XIRR（货币加权），不是简单收益率外推。
- **数据不足会说"数据不足"**：评分在净值不足时返回 `total=None` / `grade="数据不足"`，
  不会用 0 值凑出一个看起来正常的分数。

## 更完整的说明

- API 参考与已知限制：见仓库根目录 `README.md`
- 供 AI Agent 加载的 Skill 入口：`skills/fund-toolkit/SKILL.md`
