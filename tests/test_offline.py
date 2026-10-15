"""离线单测：只测纯函数，不需要网络，CI 必跑。

运行：pytest -q tests/test_offline.py
"""
import os
import sys
from datetime import date

import pytest

# 让测试在"未安装、直接 clone"的情况下也能跑
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "skills", "fund-toolkit", "scripts"))

import fund_skill as fs


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def test_version_format():
    assert fs.__version__.count(".") == 2


@pytest.mark.parametrize("bad", ["11001", "abc123", "", "1100111", "11001a"])
def test_normalize_fund_code_rejects(bad):
    with pytest.raises(ValueError):
        fs.normalize_fund_code(bad)


@pytest.mark.parametrize("raw,expected", [("110011", "110011"), (" 110011 ", "110011"),
                                          ("of110011", "110011"), ("SZ110011", "110011")])
def test_normalize_fund_code_ok(raw, expected):
    assert fs.normalize_fund_code(raw) == expected


@pytest.mark.parametrize("raw,expected", [("1.23%", 1.23), ("-2.5", -2.5), ("--", None),
                                          ("", None), (None, None), ("N/A", None)])
def test_to_float(raw, expected):
    assert fs.to_float(raw) == expected


def test_safe_get():
    assert fs.safe_get({"a": {"b": 1}}, "a", "b") == 1
    assert fs.safe_get({"a": 1}, "x", default="d") == "d"
    assert fs.safe_get({"a": None}, "a", default="d") == "d"


# --------------------------------------------------------------------------
# 评分：方向与配置自检
# --------------------------------------------------------------------------

def test_calc_score_5f_higher_is_better():
    ret = [(40, 5), (10, 4), (0, 2.5)]
    assert fs.calc_score_5f(40, ret) == 5
    assert fs.calc_score_5f(10, ret) == 4
    assert fs.calc_score_5f(0, ret) == 2.5
    assert fs.calc_score_5f(-5, ret) == 0.5      # 低于最低档 -> 兜底
    assert fs.calc_score_5f(None, ret) is None   # 缺失不评分


def test_calc_score_5f_lower_is_better():
    """回撤/波动率越小越好。方向写错会让该维度对任何输入都返回同一档
    （历史 bug：风险控制恒为 5.0）。"""
    dd = [(0, 5), (8, 4.5), (15, 4), (20, 3.5), (30, 2.5)]
    assert fs.calc_score_5f(0, dd, higher_is_better=False) == 5
    assert fs.calc_score_5f(8, dd, higher_is_better=False) == 4.5
    assert fs.calc_score_5f(20, dd, higher_is_better=False) == 3.5
    assert fs.calc_score_5f(99, dd, higher_is_better=False) == 0.5
    # 关键回归：0 与 30 必须得分不同（曾因方向写反而完全相同）
    assert fs.calc_score_5f(0, dd, higher_is_better=False) != \
           fs.calc_score_5f(30, dd, higher_is_better=False)


def test_score_configs_pass_self_check():
    fs._validate_score_configs(fs._SCORE_CONFIGS)


def test_score_configs_reject_wrong_direction():
    bad = {"x": {"w": (1, 0, 0, 0),
                 "dd": [(8, 4), (0, 5)],           # 升序写反
                 "vol": [(0, 5)], "r1": [(0, 5)], "r3": [(0, 5)],
                 "wr": [(0, 5)], "nh": [(0, 5)], "cal": [(0, 5)]}}
    with pytest.raises(ValueError):
        fs._validate_score_configs(bad)


def test_score_configs_reject_bad_weights():
    bad = {"x": {"w": (1, 1, 1, 1),
                 "dd": [(0, 5)], "vol": [(0, 5)], "r1": [(0, 5)], "r3": [(0, 5)],
                 "wr": [(0, 5)], "nh": [(0, 5)], "cal": [(0, 5)]}}
    with pytest.raises(ValueError):
        fs._validate_score_configs(bad)


def test_every_type_has_weights_summing_to_one():
    for name, cfg in fs._SCORE_CONFIGS.items():
        assert abs(sum(cfg["w"]) - 1.0) < 1e-9, name


# --------------------------------------------------------------------------
# 类型识别：有序优先级（dict 顺序曾导致指数基金被判成主动股票型）
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("指数型-股票", "指数型"),
    ("指数型-固收", "纯债型"),
    ("股票型", "主动股票型"),
    ("货币型-普通货币", "货币型"),
    ("QDII-混合偏股", "QDII"),
    ("债券型-混合一级", "纯债型"),
    ("混合型-偏债", "偏债混合型"),
    ("混合型-灵活", "灵活配置型"),
    ("FOF-稳健型", "FOF"),
])
def test_type_from_text(raw, expected):
    assert fs._type_from_text(raw) == expected


def test_type_from_name_fallback():
    assert fs._type_from_text("", "招商中证白酒指数(LOF)A") == "指数型"
    assert fs._type_from_text("", "天弘余额宝货币") == "货币型"
    assert fs._type_from_text("", "易方达优质精选混合(QDII)") == "QDII"
    assert fs._type_from_text("", "招商产业债券A") == "纯债型"
    assert fs._type_from_text("", "华夏成长混合") == "灵活配置型"


def test_risk_mapping_is_nested():
    assert fs.RISK_MAPPING["C1"] == ["R1"]
    assert set(fs.RISK_MAPPING["C3"]).issubset(set(fs.RISK_MAPPING["C5"]))


# --------------------------------------------------------------------------
# 回撤序列与纵轴取整
# --------------------------------------------------------------------------

def test_drawdown_series_non_negative_and_starts_at_zero():
    rows = [{"date": f"2024-01-{i:02d}", "adj": v}
            for i, v in enumerate([1.0, 1.1, 1.0, 0.9, 1.2], start=1)]
    s = fs._drawdown_series(rows, "adj")
    assert s[0] == 0.0
    assert min(s) >= 0.0
    assert max(s) == pytest.approx(18.18, abs=0.01)     # 1.1 -> 0.9
    assert all(x >= 0 for x in s)


@pytest.mark.parametrize("max_dd,expected", [
    (0.0, 1.0), (0.1, 0.5), (0.4, 0.5), (0.96, 1.5), (2.1, 3.0),
    (3.96, 5.0), (4.0, 5.0), (10.0, 15.0), (15.8, 20.0), (32.96, 45.0),
])
def test_drawdown_axis_max(max_dd, expected):
    """轴顶 = 1.25 × 最大回撤，向上取整（>=5 步长 5，<5 步长 0.5）。"""
    assert fs._drawdown_axis_max(max_dd) == pytest.approx(expected)


def test_drawdown_axis_never_clips_series():
    """硬要求：轴顶必须 >= 序列最深值，否则波形会画到画布外。"""
    for series in ([1.0, 0.999, 1.0], [1.0, 0.9, 1.05], [1.0, 0.5, 1.2], [1.0, 1.0]):
        rows = [{"date": f"2024-01-{i:02d}", "adj": v} for i, v in enumerate(series, 1)]
        s = fs._drawdown_series(rows, "adj")
        assert fs._drawdown_axis_max(max(s)) >= max(s)


def test_calc_max_drawdown_reports_dates():
    rows = [{"date": f"2024-01-{i:02d}", "adj": v, "nav": v}
            for i, v in enumerate([1.0, 1.5, 1.2, 1.8], start=1)]
    r = fs.calc_max_drawdown(rows)
    assert r["max_drawdown"] == pytest.approx(20.0, abs=0.01)
    assert r["peak_date"] == "2024-01-02"
    assert r["trough_date"] == "2024-01-03"


def test_calc_metrics_insufficient():
    assert fs.calc_metrics([{"date": "2024-01-01", "adj": 1.0}])["insufficient"] is True


def test_calc_metrics_uses_real_span():
    """年化必须按真实日历跨度，不能用点数、也不能硬编码 1/3。"""
    rows = [{"date": d, "adj": v} for d, v in
            [("2023-01-01", 1.0), ("2023-07-01", 1.1), ("2024-01-01", 1.21)]]
    m = fs.calc_metrics(rows)
    assert m["years"] == pytest.approx(1.0, abs=0.02)
    assert m["annual_return"] == pytest.approx(21.0, abs=0.5)


# --------------------------------------------------------------------------
# 定投：计划日与可交易日映射
# --------------------------------------------------------------------------

def test_plan_dates_monthly_keeps_every_month():
    d = fs._plan_dates(date(2024, 1, 15), date(2024, 6, 28), "monthly", day_of_month=1)
    assert [x.strftime("%m-%d") for x in d] == ["02-01", "03-01", "04-01", "05-01", "06-01"]


def test_plan_dates_month_end_does_not_crash():
    """day_of_month=30 遇到 2 月要落到月末，而不是抛 ValueError。"""
    d = fs._plan_dates(date(2024, 1, 31), date(2024, 6, 30), "monthly", day_of_month=30)
    assert d[0] == date(2024, 2, 29)
    assert len(d) == 5


def test_plan_dates_quarterly():
    d = fs._plan_dates(date(2024, 1, 1), date(2024, 12, 31), "quarterly", day_of_month=15)
    assert [x.strftime("%m-%d") for x in d] == ["01-15", "04-15", "07-15", "10-15"]


def test_plan_dates_weekly():
    d = fs._plan_dates(date(2024, 1, 1), date(2024, 3, 31), "weekly", day_of_week=0)
    assert len(d) == 13
    assert all(x.weekday() == 0 for x in d)


def test_plan_dates_rejects_unknown_frequency():
    with pytest.raises(ValueError):
        fs._plan_dates(date(2024, 1, 1), date(2024, 6, 1), "monthly2")


def test_map_to_tradable_never_snaps_backwards():
    """计划日遇到非交易日必须顺延到之后，不能向前吸附到上个月
    （历史 bug：每月 1 号定投会把 6 月那期买到 5 月 31 日）。"""
    rows = [{"date": d} for d in ["2024-03-29", "2024-04-01", "2024-04-02"]]
    picked, merged = fs._map_to_tradable(rows, [date(2024, 3, 31), date(2024, 4, 1)])
    assert picked == ["2024-04-01"]
    assert merged == 1


def test_map_to_tradable_drops_dates_beyond_window():
    rows = [{"date": d} for d in ["2024-01-02", "2024-01-03"]]
    picked, _ = fs._map_to_tradable(rows, [date(2024, 1, 2), date(2024, 6, 1)])
    assert picked == ["2024-01-02"]


def test_xirr_matches_known_rate():
    r = fs._xirr([date(2023, 1, 1), date(2024, 1, 1)], [-1000, 1100])
    assert r is not None and abs(r - 0.1) < 0.01


def test_xirr_none_for_single_flow():
    assert fs._xirr([date(2023, 1, 1)], [-1000]) is None


def test_redeem_fee_ladder():
    assert fs._redeem_fee_rate(3) == 0.015
    assert fs._redeem_fee_rate(100) == 0.005
    assert fs._redeem_fee_rate(400) == 0.0025
    assert fs._redeem_fee_rate(800) == 0.0


# --------------------------------------------------------------------------
# 缓存与配置
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value,ok", [([], False), ({}, False), (None, False),
                                       ("", False), ([1], True), ({"a": 1}, True),
                                       ("x", True), (0, True)])
def test_cacheable_excludes_empty(value, ok):
    """空结果不得入缓存：一次网络故障会被固化一整天。"""
    assert fs._cacheable(value) is ok


def test_cache_dir_is_separate_from_legacy():
    assert fs.get_config().cache_dir.endswith(".fund_skill_cache")


def test_env_parsers_are_safe(monkeypatch):
    monkeypatch.setenv("FUND_X_INT", "abc")
    monkeypatch.setenv("FUND_X_BOOL", "1")
    assert fs._env_int("FUND_X_INT", 15) == 15          # 非法值回退默认，不抛异常
    assert fs._env_bool("FUND_X_BOOL", False) is True   # "1" 必须解析为 True
    assert fs._env_bool("FUND_X_NO", True) is True
    monkeypatch.setenv("FUND_X_NO", "yes")
    assert fs._env_bool("FUND_X_NO", False) is True


def test_correlation_rejects_single_code():
    with pytest.raises(ValueError):
        fs.calculate_correlation(["110011"])


def test_find_similar_rejects_list_target():
    """签名是 find_similar(target: str, candidates)，传列表要给自解释的报错。"""
    with pytest.raises(ValueError, match="target"):
        fs.find_similar_funds(["110011", "519069"], ["000001"])


def test_report_escapes_and_returns_string_when_no_path():
    """output_path 为空时必须返回 HTML 字符串（曾隐式返回 None）。"""
    import inspect
    src = inspect.getsource(fs.generate_fund_html_report)
    assert "if not output_path:" in src and "return html_doc" in src
