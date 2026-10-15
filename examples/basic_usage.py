"""基础使用示例：搜索基金、查净值与持仓、看评分。
零依赖，直接运行即可（无需 pip install）：
    python examples/basic_usage.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "fund-toolkit", "scripts"))
from fund_skill import FundToolkit

tk = FundToolkit()
CODE = "110011"


def main():
    print("=" * 56)
    print("1. 搜索基金")
    print("=" * 56)
    for r in tk.search("易方达蓝筹")[:3]:
        print(f"  {r['CODE']}: {r['NAME']} ({r.get('CATEGORYDESC', '')})")

    print("\n" + "=" * 56)
    print("2. 基金基本信息")
    print("=" * 56)
    print(f"  名称: {tk.get_name(CODE)}")
    print(f"  类型: {tk.get_type(CODE)}")
    print(f"  经理: {tk.get_manager(CODE)}")
    print(f"  公司: {tk.get_company(CODE)}")

    print("\n" + "=" * 56)
    print("3. 历史净值（复权口径）")
    print("=" * 56)
    rows = tk.get_nav_history(CODE, days=365)
    print(f"  {len(rows)} 个交易日：{rows[0]['date']} ~ {rows[-1]['date']}")
    print(f"  首日  单位净值 {rows[0]['nav']}  累计净值 {rows[0]['acc']}  复权 {rows[0]['adj']}")
    print(f"  末日  单位净值 {rows[-1]['nav']}  累计净值 {rows[-1]['acc']}  复权 {rows[-1]['adj']:.4f}")
    divs = [r for r in rows if r.get("dividend")]
    if divs:
        print(f"  区间内分红 {len(divs)} 次：" +
              ", ".join(f"{d['date']} 每份{d['dividend']}元" for d in divs))

    print("\n" + "=" * 56)
    print("4. 评分（四维）")
    print("=" * 56)
    s = tk.get_score(CODE)
    print(f"  综合评分: {s['total']}/5.0   评级: {s['grade']}")
    for k, v in s["scores"].items():
        print(f"    {k}: {v}")
    d = s["details"]
    print(f"  区间年数: {d['区间年数']}   年化收益: {d['年化收益']}%")
    print(f"  最大回撤: {d['最大回撤']}% ({d['回撤区间']})   年化波动率: {d['年化波动率']}%")

    print("\n" + "=" * 56)
    print("5. 持仓（最新一期披露）")
    print("=" * 56)
    for h in tk.get_holdings(CODE)[:10]:
        print(f"  {h['code']:>8}  {h['name']:<14} {h['ratio']}%")


if __name__ == "__main__":
    main()
