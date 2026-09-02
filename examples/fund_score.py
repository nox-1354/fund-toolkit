"""基金评分示例 - 需要安装 akshare"""

from fund_toolkit import FundToolkit

tk = FundToolkit()

codes = ["110011", "519069", "000001"]

print("=" * 60)
print("基金评分对比")
print("=" * 60)

for code in codes:
    try:
        score = tk.get_score(code)
        print(f"\n{score['name']} ({code})")
        print(f"  综合评分: {score['total']}/5.0")
        print(f"  评级: {score['grade']}")
        print(f"  收益能力: {score['scores']['收益能力']}")
        print(f"  风险控制: {score['scores']['风险控制']}")
        print(f"  性价比: {score['scores']['性价比']}")
        print(f"  稳定性: {score['scores']['稳定性']}")
    except Exception as e:
        print(f"\n{code}: 评分不可用 ({e})")
