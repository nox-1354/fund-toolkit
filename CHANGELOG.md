# 更新日志

所有显著的项目变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

### 文档
- 补充国内网络下的获取与安装方式（codeload ZIP / Release wheel）
- 测试命令统一为 `python -m pytest`，并说明 Windows 下启动器不在 PATH 的情况
- 已知限制补充两处：类型归一对一级/二级债基的偏差、收益能力阈值未随区间缩放
- 新增专栏「完整演示与常见问题」链接

## [2.0.0] - 2026-10-15

> ⚠️ **破坏性变更**：本项目自 2.0.0 起是一次重写。导入名从 `fund_toolkit` 改为
> **`fund_skill`**，第三方依赖从 4 个降为 **0 个**，包结构由 `fund_toolkit/` 多模块
> 改为 `skills/fund-toolkit/` 下的自包含单文件。旧版可用标签 `v1.3.0` 取用。

### 迁移对照（1.3.0 → 2.0.0）

| 项 | 1.3.0 | 2.0.0 |
|---|---|---|
| 导入名 | `import fund_toolkit` | **`import fund_skill`** |
| 第三方依赖 | requests / pandas / numpy / beautifulsoup4（+ 可选 akshare） | **0 个**（纯标准库） |
| 本地服务 | 公司列表 / 净值排行 / 榜单需要 Node.js 服务 | **不需要**，直连上游公开接口 |
| 包结构 | `fund_toolkit/` 多模块（core / advisor / vis） | `skills/fund-toolkit/scripts/fund_skill.py` 单文件 |
| 缓存 | `~/.fund_toolkit_cache`（pickle） | `~/.fund_skill_cache`（JSON） |
| 评分口径 | 风险控制维度恒为 5.0（阈值方向写反） | 四维真实参与加权 |
| 收益口径 | 未复权单位净值 | 复权净值（含分红再投资） |
| 定投年化 | 简单收益率按数据窗复利外推 | XIRR（货币加权） |

**改名原因**：`fund_toolkit` 这个名字可能已被 site-packages 里安装的 1.3.x 占用。
若沿用同名，`import fund_toolkit` 会静默拿到旧版并给出错误结果。改名后不会再有此冲突。

### 新增
- **AI Skill 形态**：`skills/fund-toolkit/`（`SKILL.md` + `scripts/fund_skill.py`），
  Agent 可直接加载执行，无需安装任何依赖。
- **全量排行与筛选**：约 2 万只基金的排行表（25 个字段），支持按区间真实收益筛选。
- **复权净值**：`get_nav_history()` 同时返回单位净值、累计净值、复权净值与每份分红。
- **XIRR 年化**：定投回测改为货币加权收益率。
- **`max_risk` 参数**：收敛 C1-C5 的候选档位。
- **离线单测与 CI**：`tests/test_offline.py`、`tests/test_network.py`、
  `.github/workflows/ci.yml`（含零依赖自检与版本号一致性检查）。

### 变更
- **零第三方依赖**：HTTP 层改用标准库 `urllib`，统计改用 `statistics`，
  皮尔逊相关与 XIRR 为纯 Python 实现。不再需要
  requests / pandas / numpy / akshare / beautifulsoup4。
- **去掉本地服务依赖**：原先需要的 Node.js 天天基金服务（TiantianFundApi）已完全移除，
  公司列表、净值排行、榜单改为直连东财公开接口。
- **模块改名 `fund_skill`**：避免与 site-packages 里已安装的旧 `fund_toolkit`（1.3.x）同名冲突。
  同名时 `import fund_toolkit` 会**静默拿到旧版并给出错误结果**。
- **缓存**：目录从 `~/.fund_toolkit_cache` 改为 `~/.fund_skill_cache`；
  格式由 pickle 改为 JSON；新增进程内记忆层，并只缓存有效结果（空结果不入缓存）。
- **数据源优先级**：指数日线主源改为新浪，`push2his.eastmoney.com` 降为兜底
  （该域名在部分代理环境下会被稳定拦截）。
- **可视化**：HTML 报告内嵌数据改为安全转义；ECharts `setOption` 改为整图替换；
  回撤图纵轴改为按最大回撤的 1.25 倍取整（不再越界）；
  `output_path` 为空时返回 HTML 字符串而非 `None`。
- **项目结构**：实现只有一份，`pip install` 通过 `package-dir` 指向 skill 目录下的同一文件。

### 修复（1.3.0 存在的问题）
- 评分"风险控制"维度阈值方向写反，导致**恒为 5.0**、权重毫无区分度（新增配置自检防止复发）
- 全部指标基于未复权单位净值，**分红日被算成暴跌**（收益低估、回撤与波动率虚高）
- 货币基金类型识别失效 + 取数必然失败，导致 **C1 保守型永远拿不到候选**
- 指数基金被误判为主动股票型（依赖 dict 顺序）
- `get_fund_analysis` 引用未赋值变量，**100% 抛 `UnboundLocalError`**，
  连带 `quick_analysis` 与 `compare_funds` 不可用
- 不存在/近似代码**静默返回别的标的**（`999999` 会返回"网易"）
- 相关性矩阵用基金名称做键，同名基金互相覆盖；`find_similar` 把强负相关当"高度相关"
  且不排除目标自身
- 定投：估值日与"一次性投入"基准不受 `start/end` 约束（区间被静默延长）；
  "年化"非货币加权；买入日跨月向前吸附造成某月重复/次月漏买；月末参数直接崩溃；
  忽略现金分红与赎回费
- 持仓"较上季度"永远取到同一张表，变化恒为 0
- HTML 报告基准线按行数截取，整体错位约半年
- 缓存会固化空结果（一次网络故障影响一整天）
- `clear_cache(pattern)` 因文件名改为哈希而完全失效
- 环境变量非法值（如 `FUND_TIMEOUT=abc`）导致 `import` 崩溃；
  `FUND_VERIFY_SSL=1` 被错误解析为"关闭证书校验"
- 数据源一次性故障即永久熔断，进程内无恢复途径

### 移除
- `fund_toolkit/` 包（`core.py` / `advisor.py` / `vis.py`），由 `fund_skill.py` 取代
- 根目录 `SKILL.md` / `SKILL_SIMPLE.md` 两版半成品，由 `skills/fund-toolkit/SKILL.md` 取代
- `requirements.txt`（已无第三方依赖）

---

## [1.3.0] - 2026-09-02

### 新增
- 初始开源版本发布
- 11 层数据架构
- 基金搜索、净值查询、持仓分析、评分系统、定投回测、投资建议、HTML 可视化
- 依赖：`requests`, `pandas`, `numpy`, `beautifulsoup4`；可选 `akshare`；部分功能需要 Node.js 服务

---

## [1.2.0] - 2026-08-30

### 新增
- 投资建议引擎（C1-C5 风险匹配）
- 基金评分系统

---

## [1.1.0] - 2026-08-28

### 新增
- 基金持仓分析
- 定投回测功能

---

## [1.0.0] - 2026-08-25

### 新增
- 基金搜索
- 基金净值查询
- 基金公司列表
