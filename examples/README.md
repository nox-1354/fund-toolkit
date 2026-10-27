# 使用示例

五个可直接运行的示例。**不需要安装任何东西**（Python 3.8+ 即可），每个示例自带路径引导：

```bash
python examples/basic_usage.py
python examples/fund_score.py
python examples/drip_backtest.py
python examples/investment_advice.py
python examples/filter_and_correlate.py
```

## 前提条件
> Windows 下的命令用 `python`；macOS / Linux 一般用 `python3`。

## 各示例演示什么

### `basic_usage.py` — 单只基金的完整调研

从搜索到持仓走一遍：搜索基金 → 基本信息（名称/类型/经理/公司）→ 历史净值（复权口径，
含区间内分红）→ 四维评分与关键指标 → 前十大持仓。

**看什么**：`get_nav_history()` 返回的 `nav` / `acc` / `adj` 三个口径的区别；
`get_score()` 的 `scores` 与 `details` 结构。

### `fund_score.py` — 跨类型评分对比

同一张表里比较 5 只不同类型的基金（QDII / 偏股混合 / 灵活配置 / 纯债 / 货币）。

**看什么**：评分阈值是**按基金类型切换**的——纯债型的回撤阈值和股票型不是一套；
货币基金走独立口径（7 日年化 + 万份收益波动），`scores` 里部分维度为 `None`。

### `drip_backtest.py` — 定投回测

同一只基金、同一区间，比较不同金额（500/1000/2000）与不同频率（月/双周/周/季）。

**看什么**：

- `annual_return_xirr` 与 `total_return` 的区别（前者是货币加权，定投必须看它）
- `lump_sum_return`：同等金额一次性投入的收益率，两者对比才有意义
- `num_investments` 与 `planned_investments`：计划日遇到非交易日会顺延，不会漏投
- `start_date` / `end_date` 与请求区间一致（估值锚定区间末日）

### `investment_advice.py` — C1-C5 投资建议

五个风险等级各出一份建议文本，最后演示用 `max_risk` 收敛嵌套档位。

**看什么**：

- C1 给出货币基金、C2 债券基金、C3 混合、C4/C5 权益类——各档位确实落在不同风险层
- `max_risk` 能把 C5 收敛到 R2（债券）或 R4（权益）
- 输出末尾的免责声明与"R 级为推断值"的标注

### `filter_and_correlate.py` — 筛选与相关性

四个功能串起来：全市场排行 → 按区间收益筛选 → 相关性矩阵 → 相似基金。

**看什么**：

- `filter_funds(period="y1")` 用的是**近 1 年真实收益**，不是日涨幅
- 相关性矩阵用基金代码做键，并给出共同交易日数（判断可信度）
- `find_similar()` 把强**负**相关单独放进 `hedges`——那是分散标的，不是"重复配置"

## 输出要点

- **复权口径**：收益、回撤、波动率、相关性都基于复权净值（累计净值差分法，含分红再投资），
  分红日不会被算成暴跌
- **年化为真实口径**：按实际日历跨度年化；定投用 XIRR，不是简单收益率外推
- **数据不足会说"数据不足"**：评分在净值不足时返回 `total=None`、`grade="数据不足"`，
  不会用 0 值凑出一个看起来正常的分数
- **示例中的数值随行情变化**，结构与量级是稳定的

## 更完整的说明

- 功能详解与 API 参考：仓库根目录 `README.md`
- 供 AI Agent 加载的 Skill 入口：`skills/fund-toolkit/SKILL.md`
