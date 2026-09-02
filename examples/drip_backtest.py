"""定投回测示例 - 需要安装 akshare"""

from fund_toolkit import FundToolkit

tk = FundToolkit()

code = "110011"
amounts = [500, 1000, 2000]

print("=" * 60)
print("定投收益对比")
print("=" * 60)

for amount in amounts:
    result = tk.drip(code, amount=amount, frequency="monthly")
    if "error" in result:
        print(f"\n每期 {amount} 元: {result['error']}")
    else:
        print(f"\n每期 {amount} 元:")
        print(f"  总投入: {result['total_cost']:.2f} 元")
        print(f"  最终市值: {result['final_value']:.2f} 元")
        print(f"  收益率: {result['total_return']:.2f}%")
        print(f"  年化收益率: {result['annual_return']:.2f}%")
