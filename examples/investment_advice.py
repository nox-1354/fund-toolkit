"""投资建议示例 - C1~C5 风险匹配"""

from fund_toolkit import FundToolkit

tk = FundToolkit()

# 不同风险等级
risk_levels = ["C1", "C3", "C5"]
amount = 50000

for risk in risk_levels:
    print("=" * 60)
    print(f"{risk} 风险等级投资建议")
    print("=" * 60)
    advice = tk.suggest(risk, amount)
    print(advice)
    print()
