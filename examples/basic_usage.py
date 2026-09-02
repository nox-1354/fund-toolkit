"""基础使用示例 - 搜索基金、查净值、看持仓"""

from fund_toolkit import FundToolkit

tk = FundToolkit()

# 1. 搜索基金
print("=" * 50)
print("1. 搜索基金")
print("=" * 50)
results = tk.search("易方达蓝筹")
for r in results[:3]:
    print(f"  {r['CODE']}: {r['NAME']} ({r.get('CATEGORYDESC', '')})")

# 2. 获取基金信息
print("\n" + "=" * 50)
print("2. 基金基本信息")
print("=" * 50)
info = tk.get_fund("110011")
print(f"  名称: {info['NAME']}")
print(f"  类型: {info['CATEGORYDESC']}")
print(f"  公司: {info.get('FundBaseInfo', {}).get('JJGS', 'N/A')}")
print(f"  经理: {info.get('FundBaseInfo', {}).get('JJJL', 'N/A')}")

# 3. 获取最新净值
print("\n" + "=" * 50)
print("3. 最新净值")
print("=" * 50)
nav = tk.get_net_value("110011")
print(f"  净值: {nav['DWJZ']} ({nav['FSRQ']})")

# 4. 获取前十大持仓
print("\n" + "=" * 50)
print("4. 前十大持仓")
print("=" * 50)
holdings = tk.get_holdings("110011")
print(holdings.head(10))
