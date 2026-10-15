"""基金筛选 + 相关性/相似基金分析。

    python examples/filter_and_correlate.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "fund-toolkit", "scripts"))

from fund_skill import FundToolkit

tk = FundToolkit()


def main():
    print("=" * 70)
    print("1. 全市场排行（只拉排行表，最快）")
    print("=" * 70)
    for r in tk.get_rank(top=5):
        print(f"  {r['code']} {r['name'][:22]:24} 近1年 {r['y1']:>8}%  净值 {r['nav']}")

    print("\n" + "=" * 70)
    print("2. 筛选：债券型、近1年收益 3%~8%")
    print("=" * 70)
    res = tk.filter_funds(fund_type="债券型", min_return=3, max_return=8,
                          period="y1", top_n=8)
    for r in res:
        print(f"  {r['code']} {r['name'][:24]:26} 近1年 {r['period_return']:>6}%  "
              f"净值 {r['nav']:>8}  日涨幅 {r['daily']}%")

    print("\n" + "=" * 70)
    print("3. 相关性矩阵（用基金代码做键，共同交易日为准）")
    print("=" * 70)
    codes = ["110011", "519069", "000001", "217022"]
    c = tk.get_correlation(codes, days=365)
    print(f"  共同交易日: {c['common_days']} 天")
    header = "        " + "".join(f"{x:>10}" for x in c["codes"])
    print(header)
    for a in c["codes"]:
        row = "".join(f"{str(c['matrix'][(a, b)]):>10}" for b in c["codes"])
        print(f"  {a:<6}{row}")
    for code in c["codes"]:
        print(f"    {code} = {c['names'][code]}")

    print("\n" + "=" * 70)
    print("4. 相似基金（只认正相关；强负相关单独归组）")
    print("=" * 70)
    target = "110011"
    r = tk.find_similar(target, ["519069", "000001", "217022", "161725"])
    print(f"  目标: {r['target_name']} ({r['target']})   共同交易日 {r['common_days']} 天")
    for label, key in (("高度正相关（可能重复配置）", "similar"),
                       ("强负相关（可用于分散）", "hedges"),
                       ("相关性不高", "uncorrelated")):
        items = r.get(key) or []
        desc = ", ".join(f"{x['name'][:12]}({x['code']}) {x['correlation']}" for x in items) or "无"
        print(f"  {label}: {desc}")


if __name__ == "__main__":
    main()
