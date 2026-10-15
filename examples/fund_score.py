"""多基金评分对比：四维评分 + 关键指标横向比较。

    python examples/fund_score.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "fund-toolkit", "scripts"))

from fund_skill import FundToolkit

tk = FundToolkit()

# 覆盖不同风险类型，观察评分口径随类型切换
CODES = {
    "110011": "QDII 混合",
    "519069": "偏股混合",
    "000001": "灵活配置",
    "217022": "纯债",
    "000198": "货币",
}


def main():
    print("=" * 92)
    print(f"{'代码':<8}{'名称':<22}{'内部类型':<10}{'总分':>6}{'评级':<14}"
          f"{'年化':>8}{'回撤':>8}{'波动':>8}")
    print("-" * 92)
    rows = []
    for code in CODES:
        try:
            s = tk.get_score(code)
        except Exception as e:                      # 单只失败不影响整表
            print(f"{code:<8}{CODES[code]:<22}取数失败: {type(e).__name__}")
            continue
        d = s.get("details") or {}
        rows.append((code, s))
        print(f"{code:<8}{(s['name'] or '')[:20]:<22}{s['type']:<10}"
              f"{str(s['total']):>6}{s['grade']:<14}"
              f"{str(d.get('年化收益')):>8}{str(d.get('最大回撤')):>8}"
              f"{str(d.get('年化波动率')):>8}")

    print("\n四维明细")
    print("-" * 92)
    for code, s in rows:
        dims = "  ".join(f"{k}={v}" for k, v in s["scores"].items())
        print(f"  {code}  {dims}")
        if s.get("note"):
            print(f"       注: {s['note']}")

    print("\n说明：")
    print("  · 评分阈值按基金类型切换（纯债型与股票型的回撤/波动阈值不同）")
    print("  · 货币基金走独立口径（7 日年化 + 万份收益波动），不使用单位净值")
    print("  · 数据不足时 total 为 None、grade 为「数据不足」，不会给出假分数")


if __name__ == "__main__":
    main()
