"""联网冒烟测试。上游接口波动属正常，CI 里单独 job 且不阻塞。

运行：pytest -q tests/test_network.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "skills", "fund-toolkit", "scripts"))

import fund_skill as fs

pytestmark = pytest.mark.network


def test_search_and_basic_info():
    assert len(fs.search_fund("易方达蓝筹")) >= 1
    assert fs.get_fund_name("110011")
    assert fs.get_fund_type("110011")


def test_unknown_code_raises_instead_of_returning_other_security():
    """历史 bug：999999 会静默返回"网易"。"""
    with pytest.raises(fs.FundNotFoundError):
        fs.get_fund_basic_info("999999")
    assert fs.get_fund_name("999999") is None       # 容错入口仍返回 None


def test_nav_history_has_adjusted_series():
    rows = fs.get_nav_history("110011", 365)
    assert len(rows) > 100
    assert all(r.get("adj") is not None for r in rows)
    assert rows[-1]["date"] > rows[0]["date"]


def test_risk_control_score_is_not_constant():
    """历史 bug：所有基金的风险控制都恒为 5.0。"""
    scores = [fs.get_fund_score(c)["scores"]["风险控制"]
              for c in ("110011", "217022")]
    assert len(set(scores)) > 1


def test_money_fund_uses_separate_branch():
    assert fs.detect_fund_type("000198") == "货币型"
    assert fs.detect_fund_risk("000198") == "R1"
    assert fs.is_money_fund("000198")
    rows = fs.get_nav_history("000198", 90)
    assert rows[-1].get("seven_day") is not None or rows[-1].get("income_per_10k") is not None


def test_c1_recommendation_not_empty():
    """历史 bug：货币型不可达导致 C1 永远无候选。"""
    recs = fs.recommend_funds("C1", top_n=3, max_score=4)
    assert recs and all(r.risk_level == "R1" for r in recs)


def test_suggest_accepts_max_score_and_includes_disclaimer():
    """suggest 与 recommend 都要能控制评估规模；输出必须含免责声明。"""
    import inspect
    assert "max_score" in inspect.signature(fs.suggest).parameters
    text = fs.suggest("C1", amount=100000, top_n=2, max_score=4)
    assert "风险提示" in text and "不构成" in text


def test_drip_respects_window_and_xirr():
    d = fs.calculate_drip("110011", amount=1000,
                          start_date="2023-01-01", end_date="2023-12-31")
    assert d["end_date"] <= "2024-01-05"                # 区间必须被尊重
    assert d["num_investments"] == d["planned_investments"]
    assert d["annual_return_xirr"] is not None


def test_index_kline_available():
    idx = fs.get_index_kline("000300", 365)
    assert len(idx) > 100
    assert idx[0][0] < idx[-1][0]


def test_holdings_has_two_tables():
    latest, prev = fs.get_holdings("110011", include_previous=True)
    assert latest and isinstance(prev, list)


def test_company_and_bigdata_lists():
    assert len(fs.get_company_list()) > 100
    assert len(fs.get_bigdata_list()) > 5


def test_report_generation():
    html = fs.generate_fund_html_report("110011")
    assert html.startswith("<!DOCTYPE html>")
    assert "var DATA=" in html
    assert "max:0," not in html                          # 回撤纵轴不再钉死在 0
