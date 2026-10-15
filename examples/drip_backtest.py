"""定投回测：不同金额/频率对比，含 XIRR 年化与一次性投入基准。

    python examples/drip_backtest.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "fund-toolkit", "scripts"))

from fund_skill import FundToolkit

tk = FundToolkit()
CODE = "110011"
START, END = "2022-01-01", "2024-12-31"


def show(d):
    print(f"  区间        : {d['start_date']} ~ {d['end_date']}"
          f"（请求 {d['requested_start']} ~ {d['requested_end']}）")
    print(f"  期数        : 计划 {d['planned_investments']} / 执行 {d['num_investments']}"
          + (f" / 顺延合并 {d['merged_investments']}" if d["merged_investments"] else ""))
    print(f"  总投入      : {d['total_cost']:,.0f} 元")
    print(f"  期末市值    : {d['final_value']:,.2f} 元（已扣赎回费 {d['redeem_fee']:,.2f}）")
    print(f"  区间收益    : {d['total_return']:+.2f}%")
    print(f"  年化(XIRR)  : {d['annual_return_xirr']:+.2f}%")
    print(f"  一次性投入  : {d['lump_sum_return']:+.2f}%   定投 vs 一次性: "
          f"{d['difference_vs_lump']:+.2f}pp")


def main():
    print("=" * 60)
    print(f"定投回测对比  {CODE} ({tk.get_name(CODE)})")
    print("=" * 60)

    print("\n【不同金额，月度】")
    for amount in (500, 1000, 2000):
        d = tk.drip(CODE, amount=amount, start_date=START, end_date=END,
                    frequency="monthly", day_of_month=1)
        print(f"\n每期 {amount} 元:")
        show(d)

    print("\n" + "=" * 60)
    print("【不同频率，每期 1000 元】")
    print("=" * 60)
    for freq, kw in [("monthly", {"day_of_month": 1}),
                     ("biweekly", {"day_of_week": 0}),
                     ("weekly", {"day_of_week": 0}),
                     ("quarterly", {"day_of_month": 1})]:
        d = tk.drip(CODE, amount=1000, start_date=START, end_date=END, frequency=freq, **kw)
        print(f"\n{freq}:")
        show(d)

    print("\n说明：")
    print("  · 区间收益为复权口径（含分红再投资），年化为 XIRR（货币加权）")
    print("  · 估值锚定区间末日；一次性投入基准取首个实际买入日，保证可比")
    print("  · 赎回费按批次持有期分档估算（<7天1.5% / 1年内0.5% / 2年内0.25% / 以上0）")
    print("  · 未计入管理费、托管费与销售服务费")


if __name__ == "__main__":
    main()
