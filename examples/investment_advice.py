"""投资建议：C1-C5 风险等级匹配。

    python examples/investment_advice.py

说明：评分需要对每只候选基金抓一次净值序列，所以这里用 max_score 限制评估数量
（默认是 max(15, top_n*2)，五个等级跑下来约一分钟）。缓存命中后会快很多。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "fund-toolkit", "scripts"))

from fund_skill import FundToolkit

tk = FundToolkit()
AMOUNT = 100000
MAX_SCORE = 8          # 每个等级最多完整评估 8 只；调小更快，调大更全


def main():
    for level in ("C1", "C2", "C3", "C4", "C5"):
        print("=" * 64)
        print(f"{level} 投资建议")
        print("=" * 64)
        print(tk.suggest(level, amount=AMOUNT, top_n=3, max_score=MAX_SCORE))
        print()

    print("=" * 64)
    print("用 max_risk 收敛档位（RISK_MAPPING 是嵌套集合，C3⊂C4⊂C5）")
    print("=" * 64)
    for level, cap in (("C5", "R2"), ("C5", "R4"), ("C3", "R1")):
        recs = tk.recommend(level, top_n=3, max_risk=cap, max_score=MAX_SCORE)
        desc = ", ".join(f"{r.name[:14]}({r.code}) {r.fund_type}/{r.risk_level}"
                         for r in recs) or "无匹配"
        print(f"  {level} + max_risk={cap}: {desc}")


if __name__ == "__main__":
    main()
