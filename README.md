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

## 亮点

- **两种形态同一份代码**：既可以当 AI Skill 加载（把 `skills/fund-toolkit/` 拷进技能目录即可），
  也可以 `pip install` 当普通库用（`import fund_skill`）。
- **复权口径**：收益、回撤、波动率、相关性统一基于复权净值（累计净值差分法，含分红再投资），
  分红日不会被算成暴跌。
- **会说实话的指标**：数据不足时明确返回"数据不足"，不会用 0 值凑出一个看似正常的分数。

## 功能一览

| 模块 | 能做什么 |
|------|---------|
| 搜索 / 信息 | 按代码或名称搜索、名称/类型/经理/公司 |
| 净值 | 单位净值、累计净值、**复权净值**、每份分红、货币基金万份收益与 7 日年化 |
| 持仓 | 最新一期持仓；可同时取上期做变化对比 |
| 排行 / 筛选 | 约 2 万只基金的全量排行与区间收益筛选 |
| 评分 | 收益能力 / 风险控制 / 性价比 / 稳定性 四维评分，按基金类型切换阈值 |
| 相关性 | 相关性矩阵、相似基金（只认正相关，强负相关单独归组） |
| 定投 | 区间回测、XIRR 年化、分红再投资、分档赎回费，与一次性投入对比 |
| 投资建议 | C1-C5 风险等级匹配 + 大类资产配置建议 |
| 可视化 | 交互式 HTML 单基金报告与多基金对比报告 |

---

## 两种用法

### 用法一：作为 AI Skill（推荐）

把 `skills/fund-toolkit/` 整个目录放进你的技能目录，Agent 读取 `SKILL.md` 后即可调用：

```python
import sys
sys.path.insert(0, r"<技能目录>/fund-toolkit/scripts")
import fund_skill
from fund_skill import FundToolkit

print(fund_skill.__file__)      # 自检：应指向上面那个路径
tk = FundToolkit()
```

### 用法二：作为 Python 库

```bash
pip install git+https://github.com/nox-1354/fund-toolkit.git
```

```python
from fund_skill import FundToolkit

tk = FundToolkit()
```


---

## 快速开始

```python
from fund_skill import FundToolkit

tk = FundToolkit()

# 搜索与基本信息
tk.search("易方达蓝筹")
tk.get_name("110011"), tk.get_type("110011"), tk.get_manager("110011")

# 历史净值（复权）
rows = tk.get_nav_history("110011", days=365)
# [{date, nav(单位净值), acc(累计净值), adj(复权净值), dividend(每份分红)}, ...]

# 持仓（本季 + 上季）
latest = tk.get_holdings("110011")
latest, prev = tk.get_holdings("110011", include_previous=True)

# 评分
s = tk.get_score("110011")
# {total, grade, type, scores{收益能力,风险控制,性价比,稳定性}, details{...}}

# 排行与筛选
tk.get_rank(top=20)
tk.filter_funds(fund_type="债券型", min_return=3, max_return=8, period="y1", top_n=10)
#   period: w1/m1/m3/m6/y1/y2/y3/ytd/since/daily —— 对应区间真实收益（%）

# 相关性
c = tk.get_correlation(["110011", "519069", "000001"], days=365)
tk.find_similar("110011", ["519069", "000001"])       # target 是单个代码字符串

# 定投回测
d = tk.drip("110011", amount=1000, start_date="2023-01-01", end_date="2023-12-31",
            frequency="monthly", day_of_month=1)
# {total_cost, final_value, total_return, annual_return_xirr, redeem_fee,
#  lump_sum_return, num_investments, planned_investments, records, note}

# 投资建议
print(tk.suggest("C3", amount=100000, top_n=5))
tk.recommend("C1", top_n=3)                  # 结构化推荐
tk.recommend("C5", max_risk="R2")            # 用 max_risk 收敛档位

# 可视化报告（不传 output_path 则返回 HTML 字符串）
tk.generate_report("110011", output_path="report.html")
tk.generate_compare_report(["110011", "519069"], output_path="compare.html")

# 其他数据
tk.get_companies()              # 215 家基金公司（含旗下基金数量）
tk.get_top_companies(10)        # 按旗下基金数量排序
tk.get_bigdata()                # 14 个大数据榜单
tk.get_index("000300", 365)     # 指数日线（报告基准）
tk.test_connection(verbose=True)
tk.clear_cache()
```

更多可运行示例见 [`examples/`](examples/)。

### 定投参数

| 参数 | 说明 |
|------|------|
| `amount` | 每期金额 |
| `start_date` / `end_date` | 回测区间，**会被严格遵守**（估值锚定区间末日） |
| `frequency` | `monthly` / `weekly` / `biweekly` / `quarterly` |
| `day_of_month` | 每月几号（超过该月天数时自动落到月末） |
| `day_of_week` | 周几（0=周一） |
| `fee_rate` | 申购费率，默认 0.0015 |
| `redeem_fee` | 是否扣赎回费，默认 True |

### 投资建议风险等级

| 等级 | 类型 | 说明 | 股/债/货币配置建议 |
|------|------|------|------------------|
| C1 | 保守型 | 追求本金安全，可接受极低收益 | 0% / 80% / 20% |
| C2 | 稳健型 | 追求稳定收益，可接受小幅波动 | 10% / 70% / 20% |
| C3 | 平衡型 | 追求资产增值，接受中等波动 | 30% / 55% / 15% |
| C4 | 积极型 | 追求较高收益，接受较大波动 | 50% / 40% / 10% |
| C5 | 进取型 | 追求高收益，接受大幅波动 | 70% / 25% / 5% |

---

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

基金公司接口需要 `deviceid`/`MobileKey`，代码运行时随机生成一个 UUID，
**不使用任何第三方凭据**。

---

## 已知限制

请在引用本工具的输出时一并说明：

1. **R1-R5 是按基金类型推断的风险等级**，不是基金合同约定的正式风险等级。
   正式评级以销售机构的风险测评结果为准。
2. **C3/C4/C5 的基金列表可能重叠**：`RISK_MAPPING` 本身是嵌套集合，且 C4/C5 的核心都是权益类，
   差别主要在**配置比例**（C4 股票 50% / C5 股票 70%）而非基金池。需要严格区分时用 `max_risk`。
3. **持仓两期披露口径不同**：季报只披露前十大，半年报/年报披露全部持仓。
   最新一期是半年报而上期是季报时，两期相减会出现大量虚假"新增"——那是披露范围差异。
4. **货币基金不用净值口径**：其单位净值恒为 1，收益按"每万份收益 / 7 日年化"计算，评分走独立分支。
5. **指数接口主源是新浪**：`push2his.eastmoney.com` 在部分网络/代理环境下会被稳定拦截
   （实测 3/3 失败），因此仅作兜底。两源都不通时，HTML 报告降级为无基准曲线，不报错中断。
6. **费率是近似**：赎回费按常见分档估算；管理费、托管费、销售服务费未计入。
7. **历史业绩不代表未来表现**；本工具不构成投资建议，输出内含免责声明。

### 性能参考

| 操作 | 耗时 |
|------|------|
| 搜索 / 基本信息 / 净值 | 单次请求，带缓存 |
| 评分（单只） | 1 次净值请求 + 缓存 |
| `get_rank(top=N)` | 1 次排行请求（约 2.7 秒），之后走缓存 |
| `filter_funds`（约 2 万只本地筛选） | 冷缓存 2~5 秒，热缓存 0.05 秒 |
| `recommend` / `suggest` | 默认最多评估 15 只基金，可用 `max_score` 调小 |

只要"收益最高的前 N 只"就用 `get_rank(top=N)`，不要用 `filter_funds`。

---

## 版本历史与升级

各版本变更、2.0.0 相对 1.3.0 的破坏性变更与已修复问题清单，见 [CHANGELOG.md](CHANGELOG.md)。
旧版代码可通过标签取用：`git checkout v1.3.0`。

---

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
├── CHANGELOG.md
└── LICENSE
```

实现只有 `fund_skill.py` 一份；`pip install` 通过 `package-dir` 指向它，
所以不存在"两份代码漂移"的可能。

---

## 开发

```bash
pip install -e ".[dev]"
pytest -q tests/test_offline.py      # 不需要网络
pytest -q tests/test_network.py      # 需要网络
```

## 致谢

- **[a-stock-data](https://github.com/simonlin1212/a-stock-data)** — 作者 simonlin1212 的 A 股全栈数据工具包。
  本项目的架构分层思路、Skill 格式与工程化方式受其启发，在此致谢 🙏
- **[TiantianFundApi](https://github.com/kouchao/TiantianFundApi)** — 天天基金 Node.js API 服务。
  早期版本依赖它运行；本项目 2.x 起已改为直连上游接口，**不再需要启动该服务**，
  但仍感谢它提供的接口线索。
- **天天基金网 (fund.eastmoney.com)** — 提供搜索、净值、持仓等公开数据接口。

## License

MIT License · Copyright (c) 2026 NOX-1354
