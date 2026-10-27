---
name: fund-toolkit
description: 当任务需要获取中国公募基金的真实数据或做基金分析时使用——基金搜索（代码/名称）、单位净值与累计净值、历史净值序列、基金持仓（重仓股与季度变化）、基金公司与基金类型、全市场净值排行与筛选、基金评分（收益/风险/性价比/稳定四维）、基金相关性分析、定投回测（含年化 XIRR）、C1-C5 风险等级投资建议、HTML 可视化报告。零依赖纯标准库实现，不需要安装任何包、不需要本地服务。适用于「查某只基金怎么样」「帮我筛选债券基金」「这只基金和那只有多像」「定投一年收益如何」「给我一份基金报告」这类请求。
origin: custom
version: 2.0.0
---

# Fund Toolkit — 基金全栈数据工具包（Skill 自包含版 V2.0.0）

纯 HTTP 直连天天基金/东方财富公开接口。**零第三方依赖**：只用 Python 标准库
（`urllib` 做 HTTP），不需要 `requests` / `akshare` / `pandas` / `numpy`，
也不需要 Node.js 服务或任何 API key。任何 Python 3.8+ 解释器都能直接跑。

## 何时激活

用户提到以下内容时加载本 skill：

- 基金、基金代码、基金搜索、基金名称
- 净值、单位净值、累计净值、历史净值、净值走势
- 基金持仓、重仓股、前十大持仓、持仓变化
- 基金公司、基金经理、基金类型
- 基金排名、基金排行、基金筛选、基金榜单
- 基金评分、基金评级、基金对比、基金相关性
- 定投、定投回测、定投收益、定投年化
- 投资建议、风险等级、C1、C2、C3、C4、C5
- 基金报告、基金可视化、基金分析报告

## 环境要求

Python **3.8+**，只用标准库，**不需要安装任何包**。任何解释器都可以。

## 使用方式

代码在 `scripts/fund_skill.py`（单文件，自包含）。

```python
import sys
sys.path.insert(0, r"<SKILL 目录>/scripts")     # 必须指向本 skill 的 scripts
import fund_skill
from fund_skill import FundToolkit

print(fund_skill.__file__)      # 自检：应指向本 skill 的 fund_skill.py
tk = FundToolkit()
```

也支持函数式调用（`fund_skill.get_fund_score("110011")`）。

## 核心用法

```python
# 搜索与基础信息
tk.search("易方达蓝筹")                 # 按名称/代码搜索
tk.get_fund("110011")                  # 原始条目（含 FundBaseInfo 快照）
tk.get_name("110011")                  # 名称
tk.get_type("110011")                  # 上游类型，如 "QDII-混合偏股"
tk.get_manager("110011")               # 基金经理
tk.get_company("110011")               # 基金公司

# 历史净值（复权口径）
rows = tk.get_nav_history("110011", days=365)
#   [{date, nav(单位净值), acc(累计净值), adj(复权净值), dividend(每份分红)}, ...]
#   adj 是复权序列（累计净值差分法），收益/回撤/相关性都应基于它

# 持仓（页面含两期，可选都要）
tk.get_holdings("110011")                              # 最新一期
latest, prev = tk.get_holdings("110011", include_previous=True)   # 本季 + 上季

# 评分（四维：收益能力/风险控制/性价比/稳定性）
s = tk.get_score("110011", days=365)
#   {total, grade, type, scores{...}, details{年化收益,最大回撤,年化波动率,卡玛比率...}}
#   数据不足时 total 为 None、grade 为「数据不足」，不会给假分

# 全市场排行与筛选
tk.get_rank(top=20)                                    # 净值排行（只拉排行表，最快）
tk.get_rank(sort_column="3nzf", top=50)                # 按近3年排序
tk.filter_funds(fund_type="债券型", min_return=3, max_return=8, period="y1", top_n=10)
#   period: w1/m1/m3/m6/y1/y2/y3/ytd/since/daily —— 对应区间真实收益（%）
#   fund_type 支持上游片段（"债券型"/"指数型-股票"）或内部类型名（"纯债型"/"QDII"）
#   约 2 万只本地筛选：冷缓存 2~5 秒，热缓存 0.05 秒。只要"收益最高的前 N 只"时用 get_rank 更快。

# 相关性（用基金代码做键，强负相关单独归组）
c = tk.get_correlation(["110011", "519069", "000001"], days=365)
#   {codes, names, common_days, matrix}
tk.find_similar("110011", ["519069", "000001"])        # 注意：target 是单个代码字符串
#   ❌ 错误写法：tk.find_similar(["110011", "519069"], candidates=[...])  -> ValueError

# 定投回测
d = tk.drip("110011", amount=1000, start_date="2023-01-01", end_date="2023-12-31",
            frequency="monthly", day_of_month=1)
#   {total_cost, final_value, total_return, annual_return_xirr, redeem_fee,
#    lump_sum_return, num_investments, planned_investments, records, note}
#   frequency: monthly / weekly / biweekly / quarterly

# 投资建议
print(tk.suggest("C3", amount=100000, top_n=5))
tk.recommend("C1", top_n=3)                    # 结构化推荐
tk.recommend("C5", max_risk="R2")              # 用 max_risk 收敛档位
tk.suggest("C1", max_score=8)                  # 用 max_score 限制评估数量（默认 15）
#   max_score 越小越快：评分需要对每只候选基金抓一次净值序列

# 可视化报告（返回文件路径；不传 output_path 则返回 HTML 字符串）
tk.generate_report("110011", output_path="report.html")
tk.generate_compare_report(["110011", "519069"], output_path="compare.html")

# 其他数据
tk.get_companies()                     # 215 家基金公司（含旗下基金数）
tk.get_top_companies(10)               # 按旗下基金数量排序
tk.get_bigdata()                       # 14 个大数据榜单
tk.get_index("000300", days=365)       # 指数日线（报告基准）
tk.test_connection(verbose=True)       # 连通性自检
tk.clear_cache()                       # 清缓存
```

## 数据源（全部为公开接口，不需要第三方 token）

| 数据 | 接口 |
|---|---|
| 搜索 | `fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx` |
| 历史净值 / 分红 | `fund.eastmoney.com/pingzhongdata/{code}.js` |
| 全量类型表（28065 只） | `fund.eastmoney.com/js/fundcode_search.js` |
| 全量排行（20580 只 × 25 字段） | `fund.eastmoney.com/data/rankhandler.aspx` |
| 基金公司（215 家） | `fundmobapi.eastmoney.com/FundMApi/FundCompanyBaseList.ashx` |
| 大数据榜单 | `appconfig2.1234567.com.cn/config/BigDataList` |
| 基金持仓 | `fundf10.eastmoney.com/FundArchivesDatas.aspx` |
| 指数日线 | 主：新浪 `money.finance.sina.com.cn`；备：`push2his.eastmoney.com/api/qt/stock/kline/get` |

基金公司接口需要 `deviceid`/`MobileKey`（代码里运行时随机生成一个 UUID，**不使用任何第三方凭据**）。

## 已知限制（请在回答用户时如实说明）

1. **R1-R5 是按基金类型推断的风险等级**，不是基金合同约定的正式风险等级。正式评级以销售机构的风险测评结果为准。
2. **C3/C4/C5 的基金列表可能重叠**。`RISK_MAPPING` 本身是嵌套集合，且 C4/C5 的核心都是权益类(R4)——
   两者的差别主要在**配置比例**（C4 股票 50% / C5 股票 70%），不在基金池。需要严格区分时用 `max_risk` 参数。
3. **持仓两期披露口径不同**：季报只披露前十大，半年报/年报披露全部持仓。所以最新一期是半年报（常见 70+ 条）
   而上期是季报（10 条）时，两期相减会出现大量虚假"新增"——那是披露范围差异，不是真的加仓。
4. **货币基金不用净值口径**：其单位净值恒为 1，收益按"每万份收益 / 7 日年化"计算，评分也走独立分支。
5. **指数接口**：主源用新浪，`push2his.eastmoney.com` 作为兜底——该域名在部分网络/代理环境下会被稳定拦截
   （实测 3/3 失败），放主源会让每次未命中缓存都白等一轮重试。
   两源都不通时，HTML 报告会自动降级为无基准曲线，不会报错中断。
6. **历史业绩不代表未来表现**；本工具不构成投资建议，输出中已内含免责声明。
7. 定投回测的赎回费按常见分档（<7 天 1.5%、7 天~1 年 0.5%、1~2 年 0.25%、≥2 年 0）估算，
   管理费/托管费/销售服务费未计入。
8. **性能**：除 `filter_funds`（约 2 万只本地筛选，冷缓存 2~5 秒、热缓存 0.05 秒）外，
   其余接口基本是单次网络请求 + 缓存。`recommend_funds` / `suggest` 默认最多对 15 只基金
   做完整评分（每只一次净值请求），要更快可调小 `max_score`。
   只要“收益最高的前 N 只”就用 `get_rank(top=N)`，不要用 `filter_funds`。
9. **类型归一的顺序偏差**：`纯债型` 的关键词包含「债券型」，且它排在 `偏债混合型` 之前，
   因此上游类型为 `债券型-混合一级 / 二级` 的一级、二级债基会被归为 `纯债型`，
   `偏债混合型` 规则里的「混合一级 / 二级」实际不会生效。这类基金波动高于纯债，
   用纯债阈值评分会偏低。
10. **收益能力阈值未随区间缩放**：该维度用区间总收益对比按一年期设计的阈值，
   `days` 明显小于 365 时（如 90 天）会系统性偏低。

## 常见坑

| 现象 | 处理 |
|---|---|
| 想 import 时找到了别的东西 | 本 skill 的模块名是 `fund_skill`，不是 `fund_toolkit`。导入后 `print(fund_skill.__file__)` 应指向本 skill 的 scripts 目录 |
| `find_similar` 报 `ValueError: 无效的基金代码` | 把候选列表传给了 `target`。正确写法：`find_similar("110011", ["519069", "000001"])` |
| `filter_funds` 慢 | 它对约 2 万只基金做本地筛选：冷缓存 2~5 秒、热缓存 0.05 秒。只要"收益最高的前 N 只"就用 `get_rank(top=N)` |
| 指数基准线缺失 | 主源是新浪，`push2his.eastmoney.com` 仅作兜底（该域名常被代理拦截）；两源都不通时报告降级为无基准曲线，不会中断 |
| 回撤波形超出画布 | 回撤序列是**回撤深度（非负数，0 = 净值新高）**，纵轴上限取 `1.25 × 最大回撤` 向上取整（≥5 用 5 为步长，<5 用 0.5 为步长），不会越界 |
| 调用脚本输出被吞掉 | 不要用 `sys.stdout = io.TextIOWrapper(...)` 重新包装 stdout（缓冲会吞输出）。用 `print(..., flush=True)` |
| 脚本末尾调 `clear_cache()` 后非零退出 | 删文件可能被沙箱/杀软拒绝。`clear_cache()` 已逐文件容错（返回成功数并记 warning，不抛异常），但验证脚本里最好别清缓存；要禁缓存用 `FUND_CACHE_ENABLED=0` |
| 缓存位置与调整 | 默认 `~/.fund_skill_cache`；`FUND_CACHE_TTL` 调 TTL，`tk.clear_cache()` 清理 |

## 目录结构

```
fund-toolkit/
├── SKILL.md                 # 本文件（Skill 入口）
└── scripts/
    └── fund_skill.py        # 自包含单文件实现
```

