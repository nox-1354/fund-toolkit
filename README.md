<p align="center">
  <h1 align="center">Fund Toolkit</h1>
</p>

<p align="center">
  基金全栈数据工具包 —— 既是 Python 库，也是 AI Skill
</p>

<p align="center">
  直连天天基金/东方财富公开接口：<b>不需要本地服务，也不需要安装任何第三方包</b>，Python 3.8+ 即可运行。
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="License"></a>
  <a href="https://github.com/nox-1354/fund-toolkit"><img src="https://img.shields.io/github/stars/nox-1354/fund-toolkit?style=social" alt="Stars"></a>
</p>

---

## 功能一览

| 模块 | 能做什么 |
|------|---------|
| 搜索 / 信息 | 按代码或名称搜索、名称/类型/基金经理/基金公司 |
| 净值 | 单位净值、累计净值、**复权净值**、每份分红；货币基金万份收益与 7 日年化 |
| 持仓 | 最新一期持仓；可同时取上一期做变化对比 |
| 排行 / 筛选 | 约 2 万只基金的全量排行；按区间真实收益筛选 |
| 评分 | 收益能力 / 风险控制 / 性价比 / 稳定性 四维评分，阈值按基金类型切换 |
| 相关性 | 相关性矩阵；相似基金（只认正相关，强负相关单独归组） |
| 定投 | 区间回测、XIRR 年化、分红再投资、分档赎回费、与一次性投入对比 |
| 投资建议 | C1-C5 风险等级匹配 + 大类资产配置建议 |
| 可视化 | 交互式 HTML 单基金报告与多基金对比报告 |

## 安装与引入

**用法一：作为 AI Skill（推荐）** —— 把 `skills/fund-toolkit/` 整个目录放进你的技能目录：

```python
import sys
sys.path.insert(0, r"<技能目录>/fund-toolkit/scripts")
from fund_skill import FundToolkit

tk = FundToolkit()
```

**用法二：作为 Python 库**

```bash
pip install git+https://github.com/nox-1354/fund-toolkit.git
```

```python
from fund_skill import FundToolkit

tk = FundToolkit()
```

## 快速开始

它将为您提供一个完整的调研流程，从搜索到出报告：

```python
from fund_skill import FundToolkit

tk = FundToolkit()
code = "110011"

# 1. 搜索与基本信息
tk.search("易方达蓝筹")[:3]
print(tk.get_name(code), tk.get_type(code), tk.get_manager(code))

# 2. 近一年净值（复权口径）
rows = tk.get_nav_history(code, days=365)
print(f"{len(rows)} 个交易日，区间 {rows[0]['date']} ~ {rows[-1]['date']}")

# 3. 评分
s = tk.get_score(code)
print(s["total"], s["grade"], s["scores"])

# 4. 持仓
for h in tk.get_holdings(code)[:5]:
    print(h["code"], h["name"], h["ratio"], "%")

# 5. 出报告
tk.generate_report(code, output_path="report.html")
```

## 功能详解

> 下面示例中的数值都是**真实输出**，用来展示返回结构和量级；行情每天变化，数值会随之变动，仅作为参考。

### 搜索与基础信息

支持基金代码或名称搜索。`get_fund()` 返回上游原始条目（含净值快照）；其余几个是常用字段的快捷方式。

```python
tk.search("易方达蓝筹")        # [{'CODE': '005827', 'NAME': '易方达蓝筹精选混合', ...}, ...]
tk.search("110011")            # 也可以直接用代码搜
tk.get_fund("110011")          # 原始条目，含 FundBaseInfo（净值/经理/公司/是否可买）
tk.get_name("110011")          # '易方达优质精选混合(QDII)'
tk.get_type("110011")          # 'QDII-混合偏股'（上游细粒度类型）
tk.get_manager("110011")       # '张坤,彭珂'
tk.get_company("110011")       # '易方达基金'
```

> 代码不存在时**抛 `FundNotFoundError`**。

### 历史净值与复权

一次返回单位净值、累计净值、**复权净值**和当日分红，所有收益/回撤/波动/相关性都基于复权净值。

```python
rows = tk.get_nav_history("110011", days=365)
rows[0]
# {'date': '2025-10-15', 'nav': 5.6399, 'acc': 7.4299, 'adj': 1.0, 'dividend': None}

# 区间内有分红时，dividend 为该日每份派现金额
[r for r in tk.get_nav_history("110008", days=1500) if r.get("dividend")]
# [{'date': '2023-11-23', 'nav': 1.3437, 'acc': 2.4603, 'dividend': 0.033, ...}, ...]
```

**货币基金走独立口径**（单位净值恒为1）：

```python
tk.get_nav_history("000198", days=30)[-1]
# {..., 'nav': None, 'income_per_10k': 0.229, 'seven_day': 0.82}   ← 万份收益 / 7 日年化
tk.is_money_fund("000198")     # True
```
### 基金持仓

```python
latest = tk.get_holdings("110011")
# [{'code': '01179', 'name': '华住集团-S', 'ratio': 9.41}, ...]

latest, previous = tk.get_holdings("110011", include_previous=True)
# 两期分别返回，可自行对比
```

> ⚠️ 季报只披露前十大，半年报/年报披露全部持仓。最新一期是半年报而上期是季报时，
> 两期直接相减会出现大量虚假"新增"，经验证为披露范围差异，并非真实加仓。

### 排行与筛选

`get_rank` 只拉一次排行表，最快；`filter_funds` 在本地对约 2 万只做筛选。

```python
tk.get_rank(top=10)
# [{'code': '002910', 'name': '易方达供给改革混合', 'nav': '7.5905',
#   'daily': '-2.6', 'm1': '...', 'y1': '141.34', ...}, ...]

tk.get_rank(sort_column="3nzf", top=10)      # 按近3年收益排序

tk.filter_funds(fund_type="债券型", min_return=3, max_return=8, period="y1", top_n=5)
# 每项在排行字段之外多一个 period_return（该区间收益，%）
```

`period` 可选：`w1` `m1` `m3` `m6` `y1` `y2` `y3` `ytd` `since` `daily`，都是**该区间的真实收益**。
`sort_column` 与 `period` 同义。

### 评分

四维评分，**阈值按基金类型切换**（纯债型和股票型的回撤/波动标准不同）：

```python
s = tk.get_score("110011")
s["total"]      # 1.69
s["grade"]      # '⭐ 不推荐'
s["type"]       # 'QDII'
s["scores"]     # {'收益能力': 1, '风险控制': 3.2, '性价比': 0.5, '稳定性': 2.2}
s["details"]    # {'区间年数': 1.0, '年化收益': -29.35, '最大回撤': 32.96,
                #  '回撤区间': '2025-11-13 → 2026-06-26', '年化波动率': 15.7, ...}
```

内部类型共 11 种，每种一套阈值：
`主动股票型` `指数型` `偏股混合型` `偏债混合型` `灵活配置型` `纯债型` `可转债型` `货币型` `FOF` `QDII` `商品型`。

如果您想知道某只基金被归到哪一类、推断风险等级是多少：

```python
tk.get_type("217022")       # '债券型-混合一级'   上游原始类型
tk.detect_type("217022")    # '纯债型'            归一后的内部类型（评分按它选阈值）
tk.detect_type("161725")    # '指数型'（不会被误判成主动股票型）
tk.detect_risk("217022")    # 'R2'                推断风险等级
```

- 数据不足时 `total` 为 `None`、`grade` 为「数据不足」
- 部分维度缺失时按可用维度加权，并在 `note` 里说明
- 货币基金按 7 日年化与万份收益波动评分，不走净值口径

```python
tk.get_metrics("110011", days=365)     # 只要指标不要评分
# {'years': 1.0, 'total_return': -29.35, 'annual_return': -29.35,
#  'max_drawdown': 32.96, 'volatility': 15.7, 'win_rate': ..., 'calmar': ...}
```

### 相关性

用**基金代码**做键（同名基金不会互相覆盖），并回传共同交易日数供判断可信度。

```python
c = tk.get_correlation(["110011", "519069", "000001", "217022"], days=365)
c["common_days"]                    # 242
c["matrix"][("519069", "000001")]   # 0.682
c["names"]                          # {'110011': '易方达优质精选混合(QDII)', ...}
```

相似基金：只把**正相关**算作"可能重复配置"，强负相关单独归组。

```python
r = tk.find_similar("110011", ["519069", "000001", "217022", "161725"])
r["similar"]        # [{'code': '161725', 'name': '招商中证白酒指数(LOF)A', 'correlation': 0.718}]
r["hedges"]         # 强负相关（相关系数 <= -threshold）
r["uncorrelated"]   # 相关性不高
```

> 注意签名：`find_similar(target, candidates)` ， `target` 是**单个**代码字符串。

### 定投回测

```python
d = tk.drip("110011", amount=1000,
            start_date="2023-01-01", end_date="2023-12-31",
            frequency="monthly", day_of_month=1)

d["total_cost"]            # 11000.0       总投入
d["final_value"]           # 9207.75        期末市值（已扣赎回费）
d["total_return"]          # -16.29         区间收益率 %
d["annual_return_xirr"]    # -30.8          年化（货币加权，XIRR）
d["lump_sum_return"]       # -28.19         同等金额一次性投入的收益率
d["difference_vs_lump"]    # 11.89          定投 vs 一次性（百分点）
d["num_investments"]       # 11             实际执行期数
d["planned_investments"]   # 11             计划期数
d["records"]               # 每期明细：日期/净值/金额/份额/到估值日的增长倍数
d["note"]                  # 口径与顺延合并说明
```

| 参数 | 说明 |
|------|------|
| `amount` | 每期金额 |
| `start_date` / `end_date` | 回测区间，**会被严格遵守**（估值锚定区间末日） |
| `frequency` | `monthly` / `weekly` / `biweekly` / `quarterly` |
| `day_of_month` | 每月几号；超过该月天数时自动落到月末 |
| `day_of_week` | 周几（0 = 周一） |
| `fee_rate` | 申购费率，默认 0.0015 |
| `redeem_fee` | 是否扣赎回费，默认 `True` |

几点口径：

- **年化是 XIRR**（货币加权）。定投是分批投入，用"总收益/总投入"再复利外推会明显失真
- **分红计入**：通过复权因子自动再投资，不会凭空消失
- **买入日顺延**：计划日遇到非交易日会取之后第一个有净值的日子，不会向前吸附到上个月
- **赎回费**按每批持有期分档估算（<7 天 1.5% / 1 年内 0.5% / 2 年内 0.25% / 以上 0）
- 管理费、托管费、销售服务费未计入

### 投资建议

它将按C1-C5匹配风险等级，为您给出大类资产配置与候选基金：

```python
print(tk.suggest("C3", amount=100000, top_n=5))
```

| 等级 | 类型 | 股/债/货币配置建议 |
|------|------|------------------|
| C1 | 保守型 | 0% / 80% / 20% |
| C2 | 稳健型 | 10% / 70% / 20% |
| C3 | 平衡型 | 30% / 55% / 15% |
| C4 | 积极型 | 50% / 40% / 10% |
| C5 | 进取型 | 70% / 25% / 5% |

结构化结果可用 `recommend()`，并可控制档位与评估规模：

```python
recs = tk.recommend("C1", top_n=3)
recs[0].code, recs[0].name, recs[0].fund_type, recs[0].risk_level, recs[0].score

tk.recommend("C5", max_risk="R2")      # 只看 R2 及以下，收敛嵌套的档位
tk.suggest("C3", max_score=8)          # 最多完整评估 8 只，越小越快
```

> `RISK_MAPPING` 是嵌套集合（C3⊂C4⊂C5），且 C4/C5 的核心都是权益类，
> 所以 C4 与 C5 的候选可能重叠——差别主要在**配置比例**而非基金池。需要严格区分时用 `max_risk`。

### 可视化报告

```python
tk.generate_report("110011", output_path="report.html")
tk.generate_compare_report(["110011", "519069"], output_path="compare.html")

html = tk.generate_report("110011")     # 不传路径则直接返回 HTML 字符串
```

单基金报告包含：近3月/6月/1年/3年切换、复权净值曲线 + 基准对比、
回撤深度曲线（纵轴按最大回撤的1.25倍取整）、超额收益与回撤修复状态。

基准默认按基金类型自动选（债基/货币用国债指数，其余用沪深 300），也可指定：

```python
tk.generate_report("110011", benchmark_code="000905", output_path="r.html")
```

### 其他

```python
tk.get_companies()          # 215 家基金公司（含旗下基金数、经理数、成立日）
tk.get_top_companies(10)    # 按旗下基金数量排序
tk.get_bigdata()            # 14 个大数据榜单（大家都在买、主题榜等）
tk.get_index("000300", 365) # 指数日线（报告基准用）
tk.test_connection(verbose=True)   # 连通性自检
tk.clear_cache()            # 清缓存，返回删除的文件数
```

## 数据源

全部为天天基金/东方财富公开接口，**均不需要 token**：

| 数据 | 接口 |
|---|---|
| 搜索 | `fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx` |
| 历史净值 / 分红 | `fund.eastmoney.com/pingzhongdata/{code}.js` |
| 全量类型表（28065 只） | `fund.eastmoney.com/js/fundcode_search.js` |
| 全量排行（20580 只 × 25 字段） | `fund.eastmoney.com/data/rankhandler.aspx` |
| 基金公司（215 家） | `fundmobapi.eastmoney.com/FundMApi/FundCompanyBaseList.ashx` |
| 大数据榜单 | `appconfig2.1234567.com.cn/config/BigDataList` |
| 基金持仓 | `fundf10.eastmoney.com/FundArchivesDatas.aspx` |
| 指数日线 | 主：`money.finance.sina.com.cn`；备：`push2his.eastmoney.com` |

基金公司接口需要 `deviceid`/`MobileKey`，代码运行时随机生成一个 UUID，不使用任何第三方凭据。

## 已知限制

1. **R1-R5 是按基金类型推断的风险等级**，不是基金合同约定的正式风险等级。正式评级以销售机构的风险测评结果为准。
2. **C4/C5 的候选可能重叠**（原因见上文投资建议一节）。
3. **持仓两期披露口径不同**（季报前十大 vs 半年报全部），直接相减会产生虚假"新增"。
4. **指数接口主源是新浪**：`push2his.eastmoney.com` 在部分网络/代理环境下会被稳定拦截，故仅作兜底；
   两源都不通时报告降级为无基准曲线，不会中断。
5. **费率是近似**：赎回费按分档估算，管理费/托管费/销售服务费未计入。
6. **历史业绩不代表未来表现**；本工具不构成投资建议，输出内含免责声明。

## 性能参考

| 操作 | 耗时 |
|------|------|
| 搜索 / 基本信息 / 净值 | 单次请求，带缓存 |
| 评分（单只） | 1 次净值请求 + 缓存 |
| `get_rank(top=N)` | 1 次排行请求（约 2.7 秒），之后走缓存 |
| `filter_funds`（约 2 万只本地筛选） | 冷缓存 2~5 秒，热缓存 0.05 秒 |
| `recommend` / `suggest` | 默认最多评估 15 只，用 `max_score` 调小 |

只要"收益最高的前 N 只"就用 `get_rank(top=N)`。

## 项目结构

```
fund-toolkit/
├── skills/fund-toolkit/
│   ├── SKILL.md                     # AI Skill 入口
│   └── scripts/fund_skill.py        # ★ 唯一实现（canonical）
├── examples/                        # 可运行示例
├── tests/
│   ├── test_offline.py              # 离线单测（CI 必跑）
│   └── test_network.py              # 联网冒烟（CI 不阻塞）
├── .github/workflows/ci.yml
├── pyproject.toml                   # py-modules 单模块分发（不另存副本）
└── CHANGELOG.md
```

可实现只有 `fund_skill.py` 一份；`pip install` 通过 `package-dir` 指向它，不存在两份代码漂移的可能。

## 开发

```bash
pip install -e ".[dev]"
pytest -q tests/test_offline.py      # 不需要网络
pytest -q tests/test_network.py      # 需要网络
```

## 版本历史与升级

各版本变更、2.0.0 相对 1.3.0 的破坏性变更与已修复问题清单，见 [CHANGELOG.md](CHANGELOG.md)。
旧版代码可通过标签取用：`git checkout v1.3.0`。

## 致谢

- **[a-stock-data](https://github.com/simonlin1212/a-stock-data)** — 作者 simonlin1212 的 A 股全栈数据工具包。
  本项目的分层架构思路、Skill 格式与工程化方式受其启发，在此致谢 🙏
- **[TiantianFundApi](https://github.com/kouchao/TiantianFundApi)** — 天天基金 Node.js API 服务。
  早期版本依赖它运行；2.x 起已改为直连上游接口，**不再需要启动该服务**，但仍感谢它提供的接口线索。
- **天天基金网 (fund.eastmoney.com)** — 提供搜索、净值、持仓等公开数据接口。

## License

MIT License · Copyright (c) 2026 NOX-1354
