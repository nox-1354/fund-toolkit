# 使用示例

本目录包含 `fund-toolkit` 的典型使用场景，方便快速上手。

## 前提条件

### 基础功能（搜索/净值/持仓/投资建议）

```bash
pip install requests pandas numpy beautifulsoup4
```

### 完整功能（评分/定投/相关性/可视化）

```bash
pip install akshare
```

### Node.js 服务（公司列表/净值排行/主题榜单）

部分高级功能需要启动 Node.js 服务，非必须：

```bash
git clone https://github.com/kouchao/TiantianFundApi
cd TiantianFundApi
npm install
npm start  # 默认 localhost:3000
```

---

## 示例列表

| 文件 | 功能 | 依赖 |
|------|------|------|
| `basic_usage.py` | 搜索基金、查净值、看持仓 | 仅 requests |
| `investment_advice.py` | 投资建议 C1-C5 风险匹配 | 仅 requests |
| `fund_score.py` | 多基金评分对比 | akshare |
| `drip_backtest.py` | 定投收益回测 | akshare |

---

## 运行方式

```bash
# 进入项目目录
cd fund-toolkit

# 运行示例
python examples/basic_usage.py
python examples/investment_advice.py
python examples/fund_score.py
python examples/drip_backtest.py
```

---

## 输出示例

### basic_usage.py

```
1. 搜索基金
  110011: 易方达中小盘混合 (混合型-偏股)
  110006: 易方达货币A (货币型-普通货币)
  110016: 易方达货币B (货币型-普通货币)

2. 基金基本信息
  名称: 易方达中小盘混合
  类型: 混合型-偏股
  公司: 易方达基金
  经理: 张坤

3. 最新净值
  净值: 5.2345 (2026-09-01)

4. 前十大持仓
       代码      名称     占比
0   01179  华住集团-S  9.41%
1  600519    贵州茅台  9.23%
2   00883  中国海洋石油  8.46%
```

### investment_advice.py

```
C3 风险等级投资建议
📊 投资建议报告

👤 投资者类型: C3 - 平衡型：追求资产增值，接受中等波动
💰 建议金额: 50,000 元

📈 资产配置建议:
  股票: 30% | 债券: 55% | 货币: 15%
  预期年化收益: 5.0% - 9.0%
...

## 更多用法

查看完整 API 参考：[README.md](../README.md#api-参考)
