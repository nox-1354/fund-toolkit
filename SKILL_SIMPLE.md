---
name: fund-toolkit
description: 当任务需要获取基金数据时使用——搜索基金、净值查询、基金持仓、基金排名等真实数据。纯 HTTP 直连天天基金，零第三方依赖，AI 可直接在对话中执行。
origin: custom
version: 1.0.0-skill
---

# Fund Toolkit - AI 可执行版（调试中）

纯 HTTP 直连天天基金，无需安装任何 Python 包（只需 `requests`），AI 可直接在对话中调用。

---

## 何时激活

用户提到以下关键词时加载本 skill：

- 基金、基金查询、基金搜索、基金代码
- 净值、基金净值、单位净值、累计净值
- 基金持仓、持仓明细、重仓股
- 基金排名、基金收益排行、基金榜单
- 基金经理、基金公司

---

## 核心函数

### 1. 搜索基金

```python
import requests
import json

def search_fund(keyword: str) -> list:
    """
    搜索基金，支持代码或名称。
    
    Args:
        keyword: 基金代码（如 "110011"）或名称（如 "易方达"）
    
    Returns:
        list: 匹配的基金列表，每项包含 CODE, NAME, CATEGORYDESC, FundBaseInfo 等
    """
    url = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
    params = {"m": "1", "key": keyword}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://fund.eastmoney.com/"
    }
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.encoding = "utf-8"
        text = resp.text.strip()
        
        # 去掉 JSONP 包裹
        if text.endswith(")") and "(" in text:
            text = text[text.find("(") + 1:-1]
        
        data = json.loads(text)
        return data.get("Datas", [])
    except Exception as e:
        return {"error": str(e)}
```

### 2. 获取基金基本信息（含净值）

```python
def get_fund_info(code: str) -> dict:
    """
    获取基金基本信息，包含最新净值、类型、公司、经理等。
    
    Args:
        code: 6位基金代码（如 "110011"）
    
    Returns:
        dict: 基金信息，包含 name, type, nav, nav_date, manager, company, is_buyable
    """
    results = search_fund(code)
    if not results or isinstance(results, dict):
        return {"error": f"未找到基金: {code}"}
    
    # 精确匹配代码
    for item in results:
        if item.get("CODE") == code:
            break
    else:
        item = results[0]  # 取第一个
    
    nav_info = item.get("FundBaseInfo", {})
    
    return {
        "code": item.get("CODE", code),
        "name": item.get("NAME", ""),
        "type": item.get("CATEGORYDESC", ""),
        "nav": nav_info.get("DWJZ", "N/A"),
        "nav_date": nav_info.get("FSRQ", "N/A"),
        "manager": nav_info.get("JJJL", "N/A"),
        "company": nav_info.get("JJGS", "N/A"),
        "is_buyable": nav_info.get("ISBUY") == "1",
        "fund_type": nav_info.get("FTYPE", ""),
    }
```

### 3. 获取基金持仓（前十大重仓股）

```python
from bs4 import BeautifulSoup

def get_fund_holdings(code: str) -> list:
    """
    获取基金最新前十大持仓。
    
    Args:
        code: 6位基金代码（如 "110011"）
    
    Returns:
        list: 持仓列表，每项包含 stock_code, stock_name, ratio
    """
    import datetime
    
    now = datetime.datetime.now()
    url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {
        "type": "jjcc",
        "code": code,
        "topline": "100",
        "year": now.strftime("%Y"),
        "month": now.strftime("%m"),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://fundf10.eastmoney.com/ccmx_{code}.html",
    }
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', class_='w782')
        
        if not table:
            return []
        
        holdings = []
        for tr in table.find_all('tr')[1:]:  # 跳过表头
            tds = tr.find_all('td')
            if len(tds) >= 7:
                holdings.append({
                    "stock_code": tds[1].get_text(strip=True) if len(tds) > 1 else "",
                    "stock_name": tds[2].get_text(strip=True) if len(tds) > 2 else "",
                    "ratio": tds[6].get_text(strip=True) if len(tds) > 6 else "",
                })
        
        return holdings[:10]  # 只取前十大
    except Exception as e:
        return {"error": str(e)}
```

### 4. 获取基金排名（日涨幅排行）

```python
def get_fund_rank(top_n: int = 10, sort_by: str = "day") -> list:
    """
    获取基金收益排名。
    
    Args:
        top_n: 返回前 N 只基金
        sort_by: 排序方式，可选 "day"(日涨幅), "week"(周涨幅), "month"(月涨幅)
    
    Returns:
        list: 排名列表
    """
    # sort_by 映射
    sort_map = {
        "day": ("RZDF", "日涨幅"),
        "week": ("ZJL", "周涨幅"), 
        "month": ("YJL", "月涨幅"),
    }
    field, label = sort_map.get(sort_by, sort_map["day"])
    
    url = "https://fund.eastmoney.com/data/rankhandler.aspx"
    params = {
        "op": "ph",
        "dt": "kf",
        "ft": "all",
        "rs": str(top_n),
        "gs": "0",
        "sc": field,
        "st": "desc",
        "sd": "2024-01-01",
        "ed": "2026-09-02",
        "qdii": "",
        "tabSubtype": ",,,,,",
        "pi": "1",
        "pn": "1",
        "dx": "1",
        "v": "0.123456789",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://fund.eastmoney.com/data/fundranking.html",
    }
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.encoding = "utf-8"
        text = resp.text
        
        # 解析返回数据
        import re
        # 匹配 var rankData = [...]
        match = re.search(r'var\s+rankData\s*=\s*(\[.*?\]);', text, re.DOTALL)
        if not match:
            return []
        
        data = json.loads(match.group(1))
        results = []
        for item in data[:top_n]:
            parts = item.split(",")
            if len(parts) >= 6:
                results.append({
                    "code": parts[0],
                    "name": parts[1],
                    "nav": parts[2],
                    "day_change": parts[3],
                    "week_change": parts[4],
                    "month_change": parts[5],
                    "rank_label": label,
                })
        return results
    except Exception as e:
        return {"error": str(e)}
```

### 5. 获取基金经理信息

```python
def get_fund_manager(code: str) -> dict:
    """
    获取基金经理信息。
    
    Args:
        code: 6位基金代码（如 "110011"）
    
    Returns:
        dict: 经理姓名、从业年限、管理规模等
    """
    info = get_fund_info(code)
    if "error" in info:
        return info
    
    manager_name = info.get("manager", "N/A")
    if manager_name == "N/A":
        return {"manager": "N/A", "message": "未找到经理信息"}
    
    return {
        "manager": manager_name,
        "fund_code": code,
        "fund_name": info.get("name", ""),
        "company": info.get("company", ""),
    }
```

---

## 依赖安装

AI 执行这些函数前，先确认环境：

```python
# 检查依赖
try:
    import requests
except ImportError:
    print("⚠️ 需要安装 requests: pip install requests")

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("⚠️ 需要安装 beautifulsoup4: pip install beautifulsoup4")
```

---

## 使用示例

### 示例 1：搜索基金

```python
results = search_fund("易方达蓝筹")
for r in results[:3]:
    print(f"{r['CODE']}: {r['NAME']} ({r.get('CATEGORYDESC', '')})")
```

### 示例 2：查询基金净值

```python
info = get_fund_info("110011")
print(f"{info['name']} ({info['code']})")
print(f"净值: {info['nav']} ({info['nav_date']})")
print(f"经理: {info['manager']} | 公司: {info['company']}")
```

### 示例 3：查看持仓

```python
holdings = get_fund_holdings("110011")
print("前十大持仓:")
for i, h in enumerate(holdings, 1):
    print(f"  {i}. {h['stock_name']} ({h['stock_code']}) 占比: {h['ratio']}")
```

### 示例 4：查看排名

```python
rank = get_fund_rank(top_n=5, sort_by="day")
print("今日涨幅 TOP5:")
for i, r in enumerate(rank, 1):
    print(f"  {i}. {r['name']} ({r['code']}) {r['day_change']}%")
```

### 示例 5：完整工作流

```python
code = "110011"

# 基本信息
info = get_fund_info(code)
print(f"📊 {info['name']}")
print(f"  净值: {info['nav']} ({info['nav_date']})")
print(f"  类型: {info['type']}")
print(f"  经理: {info['manager']}")
print()

# 持仓
holdings = get_fund_holdings(code)
print("📈 前十大持仓:")
for i, h in enumerate(holdings, 1):
    print(f"  {i}. {h['stock_name']} 占比: {h['ratio']}")
```


## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 1.0.0-skill | 2026-09-02 | AI 可执行版，纯 HTTP 直连 |


---

## 注意事项

1. **BeautifulSoup 需要安装**：在 AI 环境里可能需要 `pip install beautifulsoup4`
2. **排名接口有时限流**：如果返回空，可能是被风控，稍等重试
3. **日涨幅排行**：收盘后更新，盘中可能不是最新
