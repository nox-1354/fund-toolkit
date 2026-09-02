"""
advisor.py- 基金投资建议引擎
基于风险等级（C1-C5）匹配基金产品（R1-R5），结合评分系统给出配置建议。
依赖：core.py
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import math

import pandas as pd

from fund_toolkit.core import (
    get_fund_score,
    get_fund_name,
    get_fund_type,
    get_fund_analysis,
    get_full_analysis,
    get_fund_history_nav,
    filter_funds,
    calculate_correlation,
    safe_get,
    normalize_fund_code,
    calculate_max_drawdown,
    search_fund,
    set_log_level,
)


# 投资者风险等级
class InvestorRisk(Enum):
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"
    C5 = "C5"

# 基金产品风险等级
class FundRisk(Enum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"

# 风险等级映射
RISK_MAPPING = {
    InvestorRisk.C1: [FundRisk.R1],
    InvestorRisk.C2: [FundRisk.R1, FundRisk.R2],
    InvestorRisk.C3: [FundRisk.R1, FundRisk.R2, FundRisk.R3],
    InvestorRisk.C4: [FundRisk.R1, FundRisk.R2, FundRisk.R3, FundRisk.R4],
    InvestorRisk.C5: [FundRisk.R1, FundRisk.R2, FundRisk.R3, FundRisk.R4, FundRisk.R5],
}

# 基金类型 -> 默认风险等级
FUND_TYPE_RISK = {
    "货币型": FundRisk.R1,
    "纯债型": FundRisk.R2,
    "偏债混合型": FundRisk.R2,
    "可转债型": FundRisk.R3,
    "灵活配置型": FundRisk.R3,
    "偏股混合型": FundRisk.R3,
    "指数型": FundRisk.R4,
    "主动股票型": FundRisk.R4,
    "QDII": FundRisk.R4,
    "FOF": FundRisk.R3,
    "商品型": FundRisk.R5,
}

# 各风险等级的股债配置建议
ASSET_ALLOCATION = {
    InvestorRisk.C1: {"股票": 0, "债券": 80, "货币": 20},
    InvestorRisk.C2: {"股票": 10, "债券": 70, "货币": 20},
    InvestorRisk.C3: {"股票": 30, "债券": 55, "货币": 15},
    InvestorRisk.C4: {"股票": 50, "债券": 40, "货币": 10},
    InvestorRisk.C5: {"股票": 70, "债券": 25, "货币": 5},
}

# 各风险等级的预期年化收益参考
EXPECTED_RETURN = {
    InvestorRisk.C1: (2.0, 4.0),
    InvestorRisk.C2: (3.0, 5.5),
    InvestorRisk.C3: (5.0, 9.0),
    InvestorRisk.C4: (8.0, 14.0),
    InvestorRisk.C5: (12.0, 20.0),
}

@dataclass
class FundRecommendation:
    code: str
    name: str
    fund_type: str
    risk_level: FundRisk
    score: float
    grade: str
    reason: str
    suitable: bool
    max_drawdown: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    annual_return: Optional[float] = None
    volatility: Optional[float] = None

@dataclass
class PortfolioSuggestion:
    investor_type: InvestorRisk
    description: str
    funds: List[FundRecommendation]
    allocation: Dict[str, float]
    asset_allocation: Dict[str, int]
    expected_return_range: Tuple[float, float]
    expected_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    correlation_matrix: Optional[pd.DataFrame] = None
    sharpe_ratio: Optional[float] = None

def detect_fund_risk(code: str) -> FundRisk:
    fund_type = get_fund_type(code) or ""
    for ftype, risk in FUND_TYPE_RISK.items():
        if ftype in fund_type:
            return risk
    return FundRisk.R3

def get_risk_level_description(risk: FundRisk) -> str:
    descriptions = {
        FundRisk.R1: "低风险：货币基金、短债基金，本金几乎无风险",
        FundRisk.R2: "中低风险：纯债基金、一级债基，波动较小",
        FundRisk.R3: "中风险：混合基金、可转债基金，有一定波动",
        FundRisk.R4: "中高风险：股票基金、指数基金，波动较大",
        FundRisk.R5: "高风险：商品基金、行业主题基金，波动极大",
    }
    return descriptions.get(risk, "未知风险")

def get_investor_type_description(risk: InvestorRisk) -> str:
    descriptions = {
        InvestorRisk.C1: "保守型：追求本金安全，可接受极低收益",
        InvestorRisk.C2: "稳健型：追求稳定收益，可接受小幅波动",
        InvestorRisk.C3: "平衡型：追求资产增值，接受中等波动",
        InvestorRisk.C4: "积极型：追求较高收益，接受较大波动",
        InvestorRisk.C5: "进取型：追求高收益，接受大幅波动",
    }
    return descriptions.get(risk, "未知类型")

def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.025) -> float:
    """计算夏普比率"""
    if returns.empty or len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / 252
    if excess.std() == 0:
        return 0.0
    return (excess.mean() / excess.std()) * math.sqrt(252)

def get_fund_metrics(code: str) -> Dict[str, Any]:
    """获取基金详细指标"""
    metrics = {"max_drawdown": 0.0, "sharpe_ratio": 0.0, "annual_return": 0.0, "volatility": 0.0}

    try:
        nav_df = get_fund_history_nav(code, 365)
        if not nav_df.empty and len(nav_df) > 1:
            nav = nav_df['单位净值'].values
            # 年化收益率
            start_nav, end_nav = nav[0], nav[-1]
            days = len(nav)
            if start_nav > 0:
                total_return = (end_nav / start_nav - 1)
                metrics["annual_return"] = ((1 + total_return) ** (365 / days) - 1) * 100

            # 最大回撤
            metrics["max_drawdown"] = calculate_max_drawdown(nav_df)

            # 日收益率
            daily_returns = pd.Series(nav).pct_change().dropna()
            if len(daily_returns) > 1:
                metrics["volatility"] = daily_returns.std() * math.sqrt(252) * 100
                metrics["sharpe_ratio"] = calculate_sharpe_ratio(daily_returns)
    except Exception:
        pass

    return metrics

def recommend_funds(
    investor_risk: InvestorRisk,
    keywords: Optional[List[str]] = None,
    min_score: float = 3.0,
    max_drawdown: Optional[float] = None,
    min_sharpe: Optional[float] = None,
    top_n: int = 10
) -> List[FundRecommendation]:
    """
    根据投资者风险等级推荐基金
    """
    allowed_risks = RISK_MAPPING.get(investor_risk, [FundRisk.R3])

    keyword_str = " ".join(keywords) if keywords else ""
    search_results = search_fund(keyword_str) if keyword_str else []

    if not search_results:
        default_codes = ["110011", "519069", "000001", "008640", "540010"]
        for code in default_codes:
            search_results.append({"CODE": code})

    recommendations = []

    for item in search_results[:top_n * 5]:
        code = item.get("CODE") or item.get("FCODE", "")
        if not code:
            continue

        # 获取评分
        try:
            score_result = get_fund_score(code)
        except Exception:
            continue

        total_score = score_result.get("total", 0)
        if total_score < min_score:
            continue

        # 判断风险等级
        risk = detect_fund_risk(code)
        if risk not in allowed_risks:
            continue

        # 获取详细指标
        metrics = get_fund_metrics(code)

        # 筛选条件
        if max_drawdown is not None and metrics["max_drawdown"] > max_drawdown:
            continue
        if min_sharpe is not None and metrics["sharpe_ratio"] < min_sharpe:
            continue

        name = score_result.get("name", code)
        fund_type = score_result.get("type", "")

        reasons = []
        if total_score >= 4.5:
            reasons.append("综合评分优秀")
        elif total_score >= 4.0:
            reasons.append("综合评分良好")

        scores = score_result.get("scores", {})
        if scores.get("收益能力", 0) >= 4.0:
            reasons.append("收益能力突出")
        if scores.get("风险控制", 0) >= 4.0:
            reasons.append("风险控制优秀")
        if scores.get("性价比", 0) >= 4.0:
            reasons.append("性价比高")
        if metrics["sharpe_ratio"] >= 1.0:
            reasons.append(f"夏普比率{metrics['sharpe_ratio']:.2f}")

        reason = "、".join(reasons) if reasons else "符合风险匹配"

        recommendations.append(FundRecommendation(
            code=code,
            name=name,
            fund_type=fund_type,
            risk_level=risk,
            score=total_score,
            grade=score_result.get("grade", ""),
            reason=reason,
            suitable=True,
            max_drawdown=metrics["max_drawdown"],
            sharpe_ratio=metrics["sharpe_ratio"],
            annual_return=metrics["annual_return"],
            volatility=metrics["volatility"],
        ))

    recommendations.sort(key=lambda x: x.score, reverse=True)
    return recommendations[:top_n]

def build_portfolio(
    investor_risk: InvestorRisk,
    fund_codes: List[str],
    target_allocation: Optional[Dict[str, float]] = None
) -> PortfolioSuggestion:
    """构建投资组合"""
    if target_allocation is None:
        n = len(fund_codes)
        target_allocation = {code: 1.0 / n for code in fund_codes}

    funds = []
    total_return = 0
    max_dd = 0
    total_sharpe = 0

    for code in fund_codes:
        try:
            analysis = get_full_analysis(code)
            score_result = get_fund_score(code)
            metrics = get_fund_metrics(code)
            risk = detect_fund_risk(code)

            name = analysis.get("name", code)
            fund_type = analysis.get("type", "")
            score = score_result.get("total", 0)

            total_return += metrics.get("annual_return", 0)
            max_dd = max(max_dd, metrics.get("max_drawdown", 0))
            total_sharpe += metrics.get("sharpe_ratio", 0)

            funds.append(FundRecommendation(
                code=code,
                name=name,
                fund_type=fund_type,
                risk_level=risk,
                score=score,
                grade=score_result.get("grade", ""),
                reason=f"配置比例 {target_allocation.get(code, 0)*100:.0f}%",
                suitable=True,
                max_drawdown=metrics.get("max_drawdown"),
                sharpe_ratio=metrics.get("sharpe_ratio"),
                annual_return=metrics.get("annual_return"),
                volatility=metrics.get("volatility"),
            ))
        except Exception:
            continue

    corr_matrix = None
    if len(fund_codes) >= 2:
        try:
            corr_matrix = calculate_correlation(fund_codes, days=90)
        except Exception:
            pass

    n = len(fund_codes)
    return PortfolioSuggestion(
        investor_type=investor_risk,
        description=get_investor_type_description(investor_risk),
        funds=funds,
        allocation=target_allocation,
        asset_allocation=ASSET_ALLOCATION.get(investor_risk, ASSET_ALLOCATION[InvestorRisk.C3]),
        expected_return_range=EXPECTED_RETURN.get(investor_risk, (4.0, 8.0)),
        expected_return=total_return / n if n > 0 else None,
        max_drawdown=max_dd if max_dd > 0 else None,
        correlation_matrix=corr_matrix,
        sharpe_ratio=total_sharpe / n if n > 0 else None,
    )

def quick_suggestion(risk_level: str, amount: float = 10000) -> str:
    """快速获取投资建议（文本输出）"""
    try:
        investor_risk = InvestorRisk(risk_level.upper())
    except ValueError:
        return f"❌ 无效的风险等级: {risk_level}，请使用 C1-C5"

    recommendations = recommend_funds(
        investor_risk,
        min_score=3.0,
        max_drawdown=30.0,
        top_n=5
    )

    if not recommendations:
        return f"⚠️ 未找到匹配 {risk_level} 等级的基金，请调整筛选条件"

    # 股债配置建议
    asset_alloc = ASSET_ALLOCATION.get(investor_risk, ASSET_ALLOCATION[InvestorRisk.C3])
    exp_range = EXPECTED_RETURN.get(investor_risk, (4.0, 8.0))

    lines = [
        f"📊 投资建议报告",
        "",
        f"👤 投资者类型: {risk_level} - {get_investor_type_description(investor_risk)}",
        f"💰 建议金额: {amount:,.0f} 元",
        "",
        "📈 资产配置建议:",
        f"  股票: {asset_alloc['股票']}% | 债券: {asset_alloc['债券']}% | 货币: {asset_alloc['货币']}%",
        f"  预期年化收益: {exp_range[0]:.1f}% - {exp_range[1]:.1f}%",
        "",
        "📋 推荐基金列表:",
        "",
    ]

    total_weight = 0
    for i, rec in enumerate(recommendations, 1):
        weight = 1.0 / len(recommendations) * 100
        total_weight += weight
        invest = amount / len(recommendations)

        lines.extend([
            f"{i}. {rec.name} ({rec.code})",
            f"   类型: {rec.fund_type} | 风险: {rec.risk_level.value} | 评分: {rec.score:.1f}/5.0",
            f"   评级: {rec.grade}",
        ])

        # 显示详细指标
        metrics_parts = []
        if rec.annual_return is not None and rec.annual_return != 0:
            metrics_parts.append(f"年化{rec.annual_return:.1f}%")
        if rec.max_drawdown is not None and rec.max_drawdown > 0:
            metrics_parts.append(f"回撤{rec.max_drawdown:.1f}%")
        if rec.sharpe_ratio is not None and rec.sharpe_ratio > 0:
            metrics_parts.append(f"夏普{rec.sharpe_ratio:.2f}")
        if metrics_parts:
            lines.append(f"  指标: {', '.join(metrics_parts)}")

        lines.extend([
            f"   理由: {rec.reason}",
            f"   建议配置: {weight:.0f}% (约 {invest:.0f} 元)",
            "",
        ])

    # 组合汇总
    lines.extend([
        "📊 组合汇总:",
        f"  总配置比例: {total_weight:.0f}%",
        f"  基金数量: {len(recommendations)} 只",
    ])

    # 组合风险提示
    lines.extend([
        "",
        "⚠️ 风险提示:",
        "  · 基金投资有风险，过往业绩不代表未来表现",
        f"  · 本建议基于 {risk_level} 风险等级匹配，请根据自身情况调整",
        "  · 建议定期（每季度）重新评估组合",
        "  · 本工具仅提供参考，不构成投资建议，投资需谨慎",
    ])

    return "\n".join(lines)

def compare_risk_levels(codes: List[str]) -> str:
    """对比多只基金的风险等级匹配情况"""
    lines = ["📊 基金风险等级对照", "", f"{'代码':<8} {'名称':<14} {'类型':<10} {'风险':<5} {'建议等级':<10} {'回撤':<7} {'夏普':<6}", "-" * 75]

    for code in codes:
        name = get_fund_name(code) or code
        fund_type = get_fund_type(code) or ""
        risk = detect_fund_risk(code)
        metrics = get_fund_metrics(code)

        suggested = []
        for investor, allowed in RISK_MAPPING.items():
            if risk in allowed:
                suggested.append(investor.value)

        max_dd = f"{metrics['max_drawdown']:.1f}%" if metrics['max_drawdown'] > 0 else "N/A"
        sharpe = f"{metrics['sharpe_ratio']:.2f}" if metrics['sharpe_ratio'] > 0 else "N/A"

        lines.append(
            f"{code:<8} "
            f"{name[:12]:<14} "
            f"{fund_type[:8]:<10} "
            f"{risk.value:<5} "
            f"{'/'.join(suggested):<10} "
            f"{max_dd:<7} "
            f"{sharpe:<6}"
        )

    return "\n".join(lines)

def suggest_conservative(amount: float = 10000) -> str:
    return quick_suggestion("C1", amount)

def suggest_balanced(amount: float = 10000) -> str:
    return quick_suggestion("C3", amount)

def suggest_aggressive(amount: float = 10000) -> str:
    return quick_suggestion("C5", amount)
