"""
SKILL_FUNDCOUNT.py - 基金全栈数据工具包 V1.3

数据源优先级：直连天天基金 → Node.js本地服务 → 新浪 → akshare
参考：https://kouchao.github.io/TiantianFundApi/
"""

import os
import time
import random
import json
import logging
import pickle
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from dataclasses import dataclass, field
from functools import wraps
from datetime import datetime
from bs4 import BeautifulSoup

import requests
import pandas as pd
import numpy as np


# 日志
logger = logging.getLogger("fund_toolkit")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)

def set_log_level(level: Union[str, int]) -> None:
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.WARNING)
    logger.setLevel(level)


# 配置
@dataclass
class FundToolkitConfig:
    base_url: str = field(default_factory=lambda: os.getenv("FUND_NODE_URL", "http://localhost:3000"))
    direct_api_url: str = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
    timeout: int = int(os.getenv("FUND_TIMEOUT", "15"))
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    verify_ssl: bool = os.getenv("FUND_VERIFY_SSL", "true").lower() == "true"
    min_interval: float = float(os.getenv("FUND_MIN_INTERVAL", "0.5"))
    cache_ttl_hours: int = int(os.getenv("FUND_CACHE_TTL", "24"))
    cache_dir: Optional[str] = None
    use_akshare: bool = os.getenv("FUND_USE_AKSHARE", "true").lower() == "true"
    enable_rate_limit: bool = os.getenv("FUND_ENABLE_RATE_LIMIT", "true").lower() == "true"
    cache_enabled: bool = os.getenv("FUND_CACHE_ENABLED", "true").lower() == "true"

    def __post_init__(self):
        if self.cache_dir is None:
            self.cache_dir = str(Path.home() / ".fund_toolkit_cache")
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

_current_config = FundToolkitConfig()

def get_config() -> FundToolkitConfig:
    return _current_config

def set_config(config: FundToolkitConfig) -> None:
    global _current_config
    _current_config = config


# 异常
class FundToolkitError(Exception):
    pass

class FundConnectionError(FundToolkitError):
    pass

class FundNotFoundError(FundToolkitError):
    pass

class FundDataError(FundToolkitError):
    pass


# 数据源优先级
class DataSource:
    DIRECT = "direct"
    NODEJS = "nodejs"
    SINA = "sina"
    AKSHARE = "akshare"

DATA_SOURCE_PRIORITY = [DataSource.DIRECT, DataSource.NODEJS, DataSource.SINA, DataSource.AKSHARE]
_source_status = {src: True for src in DATA_SOURCE_PRIORITY}

def mark_source_unavailable(source: str, reason: str = "") -> None:
    _source_status[source] = False
    logger.warning(f"数据源 {source} 不可用: {reason}")

def is_source_available(source: str) -> bool:
    return _source_status.get(source, False)

# HTTP 客户端（限流：请求前检查）
_LAST_CALL_TIME = 0.0
_SESSION = None

def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({"User-Agent": get_config().user_agent})
    return _SESSION

def _rate_limit() -> None:
    if not get_config().enable_rate_limit:
        return
    elapsed = time.time() - _LAST_CALL_TIME
    if elapsed < get_config().min_interval:
        time.sleep(get_config().min_interval - elapsed + random.uniform(0.05, 0.15))

def _update_last_call() -> None:
    global _LAST_CALL_TIME
    _LAST_CALL_TIME = time.time()

def _request(url: str, params: Optional[Dict] = None, method: str = "GET",
             headers: Optional[Dict] = None, timeout: Optional[int] = None) -> requests.Response:
    _rate_limit()
    config = get_config()
    session = _get_session()
    merged_headers = session.headers.copy()
    if headers:
        merged_headers.update(headers)
    resp = session.request(method, url, params=params, headers=merged_headers,
                           timeout=timeout or config.timeout, verify=config.verify_ssl)
    _update_last_call()
    return resp


# 直连天天基金
def _direct_search(keyword: str, timeout: Optional[int] = None) -> Dict[str, Any]:
    config = get_config()
    headers = {"User-Agent": config.user_agent, "Referer": "https://fund.eastmoney.com/"}
    resp = _request(config.direct_api_url, params={"m": "1", "key": keyword},
                    headers=headers, timeout=timeout)
    resp.encoding = "utf-8"
    if resp.status_code != 200:
        raise FundConnectionError(f"直连 HTTP {resp.status_code}")
    text = resp.text.strip()
    if not text:
        raise FundDataError("直连返回空响应")
    if text.endswith(")") and "(" in text:
        text = text[text.find("(") + 1:-1].strip()
    return json.loads(text)


# Node.js 备胎
def _nodejs_request(endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    config = get_config()
    resp = _request(f"{config.base_url}{endpoint}", params=params,
                    headers={"Accept": "application/json"})
    if resp.status_code != 200:
        raise FundConnectionError(f"Node.js HTTP {resp.status_code}")
    if not resp.text:
        raise FundDataError("Node.js 返回空响应")
    return resp.json()


# 统一请求入口（自动降级）
def fund_get(endpoint: str, params: Optional[Dict] = None,
             timeout: Optional[int] = None) -> Dict[str, Any]:
    last_error = None
    for source in DATA_SOURCE_PRIORITY:
        if not is_source_available(source):
            continue
        try:
            if source == DataSource.DIRECT:
                if endpoint != "/fundSearch":
                    continue
                return _direct_search(params.get("key", ""), timeout)
            elif source == DataSource.NODEJS:
                return _nodejs_request(endpoint, params)
            elif source in (DataSource.SINA, DataSource.AKSHARE):
                continue
        except (FundConnectionError, FundDataError) as e:
            last_error = e
            mark_source_unavailable(source, str(e))
            continue
    raise FundConnectionError(f"所有数据源均不可用: {last_error}")


# 连接测试
def test_connection(verbose: bool = False) -> bool:
    try:
        _direct_search("110011", timeout=5)
        if verbose:
            print("✅ 直连成功")
        return True
    except Exception as e:
        if verbose:
            print(f"❌ 直连失败: {e}")
    try:
        _nodejs_request("/fundSearch", {"m": "1", "key": "110011"})
        if verbose:
            print("✅ Node.js 成功")
        return True
    except Exception as e:
        if verbose:
            print(f"❌ Node.js 失败: {e}")
    return False


# 缓存
def _cache_path(key: str) -> Path:
    key_hash = hashlib.md5(key.encode("utf-8")).hexdigest()
    return Path(get_config().cache_dir) / f"{key_hash}.pkl"

def cached(ttl_hours: Optional[int] = None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not get_config().cache_enabled:
                return func(*args, **kwargs)
            
            try:
                key_parts = [func.__name__]
                for a in args:
                    if isinstance(a, (pd.DataFrame, pd.Series)):
                        # DataFrame/Series 用 shape + 前3行哈希 近似标识
                        if isinstance(a, pd.DataFrame):
                            key_parts.append(f"df_{a.shape}_{hash(str(a.iloc[:3].values.tolist()))}")
                        else:
                            key_parts.append(f"series_{a.shape}_{hash(str(a.iloc[:3].values.tolist()))}")
                    else:
                        key_parts.append(str(a))
                for k, v in sorted(kwargs.items()):
                    if isinstance(v, (pd.DataFrame, pd.Series)):
                        if isinstance(v, pd.DataFrame):
                            key_parts.append(f"{k}=df_{v.shape}")
                        else:
                            key_parts.append(f"{k}=series_{v.shape}")
                    else:
                        key_parts.append(f"{k}={v}")
                cache_key = "_".join(key_parts)
            except Exception:
                return func(*args, **kwargs)
            
            path = _cache_path(cache_key)
            ttl = ttl_hours or get_config().cache_ttl_hours
            
            if path.exists():
                try:
                    age = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds()
                    if age < ttl * 3600:
                        with open(path, "rb") as f:
                            return pickle.load(f)
                except Exception as e:
                    logger.debug(f"缓存读取失败: {e}")
                    try:
                        path.unlink()
                    except Exception:
                        pass
            
            result = func(*args, **kwargs)
            
            if result is not None:
                try:
                    with open(path, "wb") as f:
                        pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
                except Exception as e:
                    logger.debug(f"缓存写入失败: {e}")
            
            return result
        return wrapper
    return decorator

def clear_cache(pattern: Optional[str] = None) -> int:
    cache_dir = Path(get_config().cache_dir)
    if not cache_dir.exists():
        return 0
    count = 0
    for f in cache_dir.glob("*.pkl"):
        if pattern is None or pattern in f.stem:
            f.unlink()
            count += 1
    return count


# Layer 0: 基础工具
def normalize_fund_code(code: str) -> str:
    code = str(code).strip()
    if code.upper().startswith(("OF", "SH", "SZ", "BJ")):
        code = code[2:]
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"无效的基金代码: {code!r}")
    return code

def safe_get(data: dict, *keys, default=None):
    result = data
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key)
        else:
            return default
    return result if result is not None else default

def safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_int(value, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default

__version__ = "1.3.0"


# Layer 1: 基金搜索与信息查询

@cached(ttl_hours=24)
def search_fund(keyword: str) -> List[Dict[str, Any]]:
    """搜索基金，支持代码或名称"""
    keyword = str(keyword).strip()
    if not keyword:
        return []
    try:
        data = fund_get("/fundSearch", params={"m": "1", "key": keyword})
        items = data.get("Datas", [])
        logger.debug(f"搜索 '{keyword}' 找到 {len(items)} 条")
        return items
    except (FundConnectionError, FundDataError) as e:
        logger.error(f"搜索失败: {e}")
        raise

def get_fund_basic_info(code: str) -> Dict[str, Any]:
    """获取基金基础信息（含净值快照）"""
    code = normalize_fund_code(code)
    results = search_fund(code)
    if not results:
        raise FundNotFoundError(f"未找到基金: {code}")
    for item in results:
        if item.get("CODE") == code:
            return item
    logger.debug(f"模糊匹配: {code} -> {results[0].get('CODE')}")
    return results[0]

def get_fund_net_value(code: str) -> Optional[Dict[str, Any]]:
    """获取基金净值信息（DWJZ, FSRQ, JJJL, JJGS 等）"""
    try:
        return safe_get(get_fund_basic_info(code), "FundBaseInfo")
    except FundNotFoundError:
        return None

def get_fund_name(code: str) -> Optional[str]:
    try:
        return safe_get(get_fund_basic_info(code), "NAME")
    except FundNotFoundError:
        return None

def get_fund_type(code: str) -> Optional[str]:
    try:
        return safe_get(get_fund_basic_info(code), "CATEGORYDESC")
    except FundNotFoundError:
        return None

def get_fund_manager(code: str) -> Optional[str]:
    return safe_get(get_fund_net_value(code), "JJJL")

def get_fund_company(code: str) -> Optional[str]:
    return safe_get(get_fund_net_value(code), "JJGS")

def format_fund_info(code: str) -> str:
    """格式化输出基金基本信息"""
    try:
        code = normalize_fund_code(code)
        info = get_fund_basic_info(code)
        nav = get_fund_net_value(code)
        lines = [
            f"📋 基金: {safe_get(info, 'NAME', default='N/A')} ({code})",
            f"类型: {safe_get(info, 'CATEGORYDESC', default='N/A')}",
        ]
        if nav:
            lines.append(f"净值: {safe_get(nav, 'DWJZ', default='N/A')} ({safe_get(nav, 'FSRQ', default='N/A')})")
            lines.append(f"公司: {safe_get(nav, 'JJGS', default='N/A')}")
            lines.append(f"经理: {safe_get(nav, 'JJJL', default='N/A')}")
            lines.append(f"可买: {'是' if safe_get(nav, 'ISBUY') == '1' else '否'}")
        return "\n".join(lines)
    except (FundNotFoundError, ValueError) as e:
        return f"❌ {e}"
    except Exception as e:
        logger.error(f"格式化失败: {e}")
        return f"❌ 获取失败: {e}"


# Layer 2: 基金公司与基金经理

@cached(ttl_hours=24)
def get_company_list() -> List[Dict[str, Any]]:
    """
    获取所有基金公司列表。
    依赖 Node.js 服务（直连不支持此接口），不可用时返回空列表并记录日志。
    """
    try:
        data = fund_get("/fundCompanyBaseList")
        if isinstance(data, dict):
            for key in ("Datas", "Data", "data"):
                if key in data:
                    return data[key]
        if isinstance(data, list):
            return data
        return []
    except FundConnectionError as e:
        logger.warning(f"公司列表获取失败（需要 Node.js 服务）: {e}")
        return []
    except Exception as e:
        logger.debug(f"公司列表获取异常: {e}")
        return []

def search_company(keyword: str) -> List[Dict[str, Any]]:
    """按名称或简称搜索基金公司"""
    keyword = str(keyword).strip()
    if not keyword:
        return []
    companies = get_company_list()
    if not companies:
        return []
    results = []
    for comp in companies:
        name = safe_get(comp, "SNAME", default="")
        abb = safe_get(comp, "ABBNAME", default="")
        if keyword.lower() in name.lower() or keyword.lower() in abb.lower():
            results.append(comp)
    logger.debug(f"搜索公司 '{keyword}' 找到 {len(results)} 条")
    return results

def get_company_by_code(company_code: str) -> Optional[Dict[str, Any]]:
    """根据公司代码获取公司信息"""
    if not company_code:
        return None
    companies = get_company_list()
    if not companies:
        return None
    for comp in companies:
        if safe_get(comp, "COMPANYCODE") == company_code:
            return comp
    return None

def format_company_info(company: Dict[str, Any]) -> str:
    """格式化公司信息"""
    if not company:
        return "❌ 未找到该公司"

    def safe_str(v):
        return str(v) if v is not None and v != '' else 'N/A'

    return (
        f"🏢 {safe_str(company.get('SNAME'))} ({safe_str(company.get('COMPANYCODE'))})\n"
        f"基金: {safe_str(company.get('FUNDCOUNT'))} 只 | 经理: {safe_str(company.get('JJRS'))} 人\n"
        f"成立: {safe_str(company.get('ESTABDATE'))}"
    )

def get_top_companies_by_fund_count(top_n: int = 10) -> List[Dict[str, Any]]:
    """获取管理基金数量最多的前 N 家公司"""
    companies = get_company_list()
    if not companies:
        return []

    def safe_int(v):
        if v is None or v == '':
            return 0
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    sorted_companies = sorted(
        companies,
        key=lambda x: safe_int(x.get("FUNDCOUNT", 0)),
        reverse=True
    )
    return sorted_companies[:top_n]


# Layer 3: 基金净值与收益率

def _fetch_net_list() -> List[Dict[str, Any]]:
    """获取净值列表（依赖 Node.js）"""
    try:
        data = fund_get("/fundMNNetNewList")
        items = data.get("Datas", [])
        if items and isinstance(items[0], list):
            return items[0]
        return items
    except (FundConnectionError, FundDataError) as e:
        logger.debug(f"净值列表获取失败: {e}")
        return []

@cached(ttl_hours=6)
def get_latest_net_value(code: str) -> Optional[Dict[str, Any]]:
    """获取单只基金最新净值"""
    code = normalize_fund_code(code)
    items = _fetch_net_list()
    for item in items:
        if item.get("FCODE") == code:
            return item
    logger.debug(f"未找到净值: {code}")
    return None

@cached(ttl_hours=6)
def get_net_value_list(top_n: int = 20) -> List[Dict[str, Any]]:
    """获取净值列表前 N 条"""
    return _fetch_net_list()[:top_n]

def search_net_value(keyword: str) -> List[Dict[str, Any]]:
    """在净值列表中搜索基金"""
    keyword = str(keyword).strip()
    if not keyword:
        return []
    items = _fetch_net_list()[:500]
    results = []
    for item in items:
        code = safe_get(item, "FCODE", default="")
        name = safe_get(item, "SHORTNAME", default="")
        if keyword in code or keyword.lower() in name.lower():
            results.append(item)
    logger.debug(f"搜索净值 '{keyword}' 找到 {len(results)} 条")
    return results

def format_net_value_list(items: List[Dict[str, Any]], title: str = "净值列表") -> str:
    """格式化输出净值列表"""
    if not items:
        return "暂无数据"
    lines = [f"📊 {title} (共{len(items)}条):"]
    for item in items[:20]:
        code = item.get("FCODE", "N/A")
        name = item.get("SHORTNAME", "N/A")[:12]
        nav = item.get("DWJZ", "N/A")
        change = item.get("RZDF", "N/A")
        lines.append(f"  {name}({code}): {nav} ({change}%)")
    return "\n".join(lines)

# Layer 4: 基金主题榜单

@cached(ttl_hours=12)
def get_fund_themes() -> List[Dict[str, Any]]:
    """获取基金主题榜单（依赖 Node.js）"""
    try:
        data = fund_get("/bigDataList")
        return data.get("datas", [])
    except (FundConnectionError, FundDataError) as e:
        logger.debug(f"主题榜单获取失败: {e}")
        return []

def get_themes_by_category(category: str = "3") -> List[Dict[str, Any]]:
    """按分类筛选主题（3=热门主题，其他分类待确认）"""
    themes = get_fund_themes()
    return [item for item in themes if safe_get(item, "ClCategory") == category]

def search_theme(keyword: str) -> List[Dict[str, Any]]:
    """按关键词搜索主题"""
    keyword = str(keyword).strip().lower()
    if not keyword:
        return []
    themes = get_fund_themes()
    results = []
    for item in themes:
        title = safe_get(item, "Title", default="").lower()
        desc = safe_get(item, "Description", default="").lower()
        if keyword in title or keyword in desc:
            results.append(item)
    logger.debug(f"搜索主题 '{keyword}' 找到 {len(results)} 条")
    return results

def format_theme(theme: Dict[str, Any]) -> str:
    """格式化单条主题"""
    if not theme:
        return "暂无数据"
    return (
        f"📌 {safe_get(theme, 'Title', default='N/A')}\n"
        f"  副标题: {safe_get(theme, 'SubTitle', default='N/A')}\n"
        f"  描述: {safe_get(theme, 'Description', default='N/A')[:60]}...\n"
        f"  基金: {safe_get(theme, 'FundName', default='N/A')}({safe_get(theme, 'FundCode', default='N/A')})\n"
        f"  收益: {safe_get(theme, 'SYL', default='N/A')} ({safe_get(theme, 'PeriodText', default='N/A')})"
    )

def format_themes(themes: List[Dict[str, Any]], title: str = "主题榜单") -> str:
    """格式化主题列表"""
    if not themes:
        return "暂无数据"
    lines = [f"📊 {title} (共{len(themes)}个):"]
    for item in themes[:10]:
        name = safe_get(item, "Title", default="N/A")
        fund = safe_get(item, "FundName", default="N/A")
        syl = safe_get(item, "SYL", default="N/A")
        period = safe_get(item, "PeriodText", default="N/A")
        lines.append(f"  {name}: {fund} {syl} ({period})")
    return "\n".join(lines)

# Layer 5: 基金完整信息（akshare 增强版）

def _get_akshare():
    """惰性加载 akshare，未安装时返回 None"""
    try:
        import akshare as ak
        return ak
    except ImportError:
        logger.debug("akshare 未安装，增强功能不可用")
        return None

@cached(ttl_hours=24)
def get_fund_full_info(code: str) -> Dict[str, Any]:
    """
    获取基金完整信息（优先 akshare，降级到基础接口）
    返回: code, name, full_name, type, company, manager,
          establish_date, scale, benchmark, investment_goal, nav, nav_date, daily_change
    """
    code = normalize_fund_code(code)
    result = {"code": code}

    # 尝试 akshare
    ak = _get_akshare()
    if ak is not None:
        try:
            df = ak.fund_individual_basic_info_xq(symbol=code)
            if df is not None and not df.empty:
                mapping = {
                    "基金代码": "code", "基金名称": "name", "基金全称": "full_name",
                    "成立时间": "establish_date", "最新规模": "scale",
                    "基金公司": "company", "基金经理": "manager", "基金类型": "type",
                    "投资目标": "investment_goal", "业绩比较基准": "benchmark",
                }
                for _, row in df.iterrows():
                    key = row.get("item", "")
                    if key in mapping:
                        result[mapping[key]] = row.get("value", "")
                return result
        except Exception as e:
            logger.debug(f"akshare 获取失败: {e}")

    # 降级到基础接口
    try:
        info = get_fund_basic_info(code)
        if info:
            result["name"] = safe_get(info, "NAME", default=f"基金{code}")
            result["type"] = safe_get(info, "CATEGORYDESC")
            nav_info = safe_get(info, "FundBaseInfo")
            if nav_info:
                result["company"] = safe_get(nav_info, "JJGS")
                result["manager"] = safe_get(nav_info, "JJJL")
                result["nav"] = safe_get(nav_info, "DWJZ")
                result["nav_date"] = safe_get(nav_info, "FSRQ")
                result["daily_change"] = safe_get(nav_info, "RZDF")
                daily_change = safe_get(nav_info, "RZDF")
                if daily_change is not None and isinstance(daily_change, str):
                    daily_change = daily_change.replace("%", "").strip()
                result["daily_change"] = daily_change
    except Exception as e:
        logger.warning(f"获取基础信息失败: {e}")

    return result

def get_fund_history_nav(code: str, days: int = 30) -> pd.DataFrame:
    """获取基金历史净值（依赖 akshare）"""
    code = normalize_fund_code(code)
    ak = _get_akshare()
    if ak is None:
        logger.debug("akshare 未安装，无法获取历史净值")
        return pd.DataFrame()
    try:
        df = ak.fund_open_fund_info_em(symbol=code)
        if df is not None and not df.empty:
            df['净值日期'] = pd.to_datetime(df['净值日期'])
            df = df.sort_values('净值日期')
            cutoff = df['净值日期'].max() - pd.Timedelta(days=days)
            return df[df['净值日期'] >= cutoff]
        return pd.DataFrame()
    except Exception as e:
        logger.debug(f"获取历史净值失败: {e}")
        return pd.DataFrame()

def get_fund_nav_series(code: str, days: int = 365) -> pd.Series:
    """获取基金净值序列（Series格式）"""
    try:
        df = get_fund_history_nav(code, days)
        if not df.empty:
            df = df.set_index('净值日期')
            return df['单位净值']
        return pd.Series()
    except Exception as e:
        logger.debug(f"获取净值序列失败: {e}")
        return pd.Series()

def calculate_max_drawdown(nav_df: pd.DataFrame) -> float:
    """计算最大回撤"""
    if nav_df.empty or '单位净值' not in nav_df.columns:
        return 0.0
    nav = nav_df['单位净值'].values
    if len(nav) == 0:
        return 0.0
    max_nav = nav[0]
    max_drawdown = 0.0
    for n in nav:
        if n > max_nav:
            max_nav = n
        drawdown = (max_nav - n) / max_nav
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return max_drawdown * 100

def format_fund_full_info(code: str) -> str:
    """格式化输出基金完整信息"""
    info = get_fund_full_info(code)
    lines = [
        f"📊 {safe_get(info, 'name', default=code)} ({code})",
        f"  类型: {safe_get(info, 'type', default='N/A')}",
        f"  公司: {safe_get(info, 'company', default='N/A')}",
        f"  经理: {safe_get(info, 'manager', default='N/A')}",
        f"  成立: {safe_get(info, 'establish_date', default='N/A')}",
        f"  规模: {safe_get(info, 'scale', default='N/A')}",
        f"  基准: {safe_get(info, 'benchmark', default='N/A')}",
    ]
    return "\n".join(lines)


# Layer 6: 基金综合分析

def get_fund_analysis(code: str) -> Dict[str, Any]:
    """
    基金快速分析（精简版）
    返回: code, name, type, manager, company, net_value, nav_date, daily_change, is_buyable
    """
    code = normalize_fund_code(code)
    result = {
        "code": code,
        "name": None, "type": None, "manager": None, "company": None,
        "net_value": None, "nav_date": None, "daily_change": None, "is_buyable": False,
    }
    
    # 从完整信息获取
    full = get_fund_full_info(code)
    if full:
        result["name"] = safe_get(full, "name")
        result["type"] = safe_get(full, "type")
        result["company"] = safe_get(full, "company")
        result["manager"] = safe_get(full, "manager")
    
    # 从历史净值获取（优先）
    nav_df = get_fund_history_nav(code, 30)
    if not nav_df.empty:
        last = nav_df.iloc[-1]
        result["net_value"] = last.get("单位净值")
        result["nav_date"] = last.get("净值日期")
        result["daily_change"] = last.get("日增长率")
        if daily_change is not None and isinstance(daily_change, str):
            daily_change = daily_change.replace("%", "").strip()
        result["daily_change"] = daily_change
    
    # fallback: 基础信息
    if not result["name"] or result["net_value"] is None:
        try:
            info = get_fund_basic_info(code)
            if info:
                result["name"] = result["name"] or safe_get(info, "NAME")
                result["type"] = result["type"] or safe_get(info, "CATEGORYDESC")
                nav_info = safe_get(info, "FundBaseInfo")
                if nav_info:
                    if result["net_value"] is None:
                        result["net_value"] = safe_get(nav_info, "DWJZ")
                    if result["nav_date"] is None:
                        result["nav_date"] = safe_get(nav_info, "FSRQ")
                    if result["daily_change"] is None:
                        result["daily_change"] = safe_get(nav_info, "RZDF")
                    result["company"] = result["company"] or safe_get(nav_info, "JJGS")
                    result["manager"] = result["manager"] or safe_get(nav_info, "JJJL")
                    result["is_buyable"] = safe_get(nav_info, "ISBUY") == "1"
        except FundNotFoundError:
            pass
    
    return result

def get_full_analysis(code: str) -> Dict[str, Any]:
    """
    基金综合分析（完整版）
    返回: code, name, type, company, manager, establish_date, scale, full_name,
          benchmark, investment_goal, nav, nav_date, daily_change, history_nav,
          max_drawdown, nav_count
    """
    code = normalize_fund_code(code)
    result = {
        "code": code,
        "name": None, "type": None, "company": None, "manager": None,
        "establish_date": None, "scale": None, "full_name": None,
        "benchmark": None, "investment_goal": None,
        "nav": None, "nav_date": None, "daily_change": None,
        "history_nav": None, "max_drawdown": None, "nav_count": 0,
    }
    
    # 基础信息
    try:
        basic = get_fund_basic_info(code)
        if basic:
            result["name"] = safe_get(basic, "NAME")
            result["type"] = safe_get(basic, "CATEGORYDESC")
            nav_info = safe_get(basic, "FundBaseInfo")
            if nav_info:
                result["nav"] = safe_get(nav_info, "DWJZ")
                result["nav_date"] = safe_get(nav_info, "FSRQ")
                result["company"] = safe_get(nav_info, "JJGS")
                result["manager"] = safe_get(nav_info, "JJJL")
    except FundNotFoundError:
        pass
    
    # 增强信息 (akshare)
    full = get_fund_full_info(code)
    if full:
        result["full_name"] = safe_get(full, "full_name")
        result["establish_date"] = safe_get(full, "establish_date") or result.get("establish_date")
        result["scale"] = safe_get(full, "scale")
        result["company"] = safe_get(full, "company") or result.get("company")
        result["manager"] = safe_get(full, "manager") or result.get("manager")
        result["type"] = safe_get(full, "type") or result.get("type")
        result["benchmark"] = safe_get(full, "benchmark")
        result["investment_goal"] = safe_get(full, "investment_goal")
    
    # 历史净值
    nav_df = get_fund_history_nav(code, 365)
    if not nav_df.empty:
        result["history_nav"] = nav_df
        result["nav_count"] = len(nav_df)
        result["max_drawdown"] = calculate_max_drawdown(nav_df)
        last = nav_df.iloc[-1]
        result["nav"] = last.get("单位净值", result.get("nav"))
        result["nav_date"] = last.get("净值日期", result.get("nav_date"))
        result["daily_change"] = last.get("日增长率", result.get("daily_change"))
        daily_change = last.get("日增长率", result.get("daily_change"))
        if daily_change is not None and isinstance(daily_change, str):
            daily_change = daily_change.replace("%", "").strip()
        result["daily_change"] = daily_change
    
    return result

def compare_funds(codes: List[str]) -> str:
    """对比多只基金"""
    results = []
    for code in codes:
        data = get_fund_analysis(code)
        results.append({
            "code": code,
            "name": safe_get(data, "name", default="N/A"),
            "nav": safe_get(data, "net_value", default="N/A"),
            "date": safe_get(data, "nav_date", default="N/A"),
            "change": safe_get(data, "daily_change", default="N/A"),
            "manager": safe_get(data, "manager", default="N/A"),
            "company": safe_get(data, "company", default="N/A"),
        })
    
    lines = ["📊 基金对比", ""]
    lines.append(f"{'代码':<8} {'名称':<16} {'净值':<10} {'日期':<12} {'日涨跌':<10} {'经理':<12}")
    lines.append("-" * 74)
    
    for r in results:
        lines.append(
            f"{r['code']:<8} "
            f"{str(r['name'])[:14]:<16} "
            f"{str(r['nav']):<10} "
            f"{str(r['date']):<12} "
            f"{str(r['change']):<10} "
            f"{str(r['manager'])[:10]:<12}"
        )
    return "\n".join(lines)

def format_fund_analysis(code: str) -> str:
    """格式化快速分析"""
    data = get_fund_analysis(code)
    lines = [
        "📊 基金分析报告", "",
        "📋 基本信息",
        f"  名称: {safe_get(data, 'name', default='N/A')} ({safe_get(data, 'code', default='N/A')})",
        f"  类型: {safe_get(data, 'type', default='N/A')}",
        f"  公司: {safe_get(data, 'company', default='N/A')}",
        f"  经理: {safe_get(data, 'manager', default='N/A')}",
        "", "💰 净值信息",
        f"  单位净值: {safe_get(data, 'net_value', default='N/A')}",
        f"  净值日期: {safe_get(data, 'nav_date', default='N/A')}",
    ]
    daily = safe_get(data, 'daily_change')
    if daily is not None:
        lines.append(f"  日涨跌幅: {daily}%")
    else:
        lines.append("  日涨跌幅: N/A")
    lines.append(f"  是否可买: {'是' if safe_get(data, 'is_buyable') else '否'}")
    return "\n".join(lines)

def format_full_analysis(code: str) -> str:
    """格式化完整分析"""
    data = get_full_analysis(code)
    lines = [
        "📊 基金综合分析报告", "",
        "📋 基本信息",
        f"  代码: {safe_get(data, 'code', default='N/A')}",
        f"  名称: {safe_get(data, 'name', default='N/A')}",
        f"  全称: {safe_get(data, 'full_name', default='N/A')}",
        f"  类型: {safe_get(data, 'type', default='N/A')}",
        f"  公司: {safe_get(data, 'company', default='N/A')}",
        f"  经理: {safe_get(data, 'manager', default='N/A')}",
        f"  成立: {safe_get(data, 'establish_date', default='N/A')}",
        f"  规模: {safe_get(data, 'scale', default='N/A')}",
        "", "💰 净值信息",
        f"  单位净值: {safe_get(data, 'nav', default='N/A')}",
        f"  净值日期: {safe_get(data, 'nav_date', default='N/A')}",
    ]
    
    dc = safe_get(data, 'daily_change', default='N/A')
    if dc != 'N/A' and dc is not None:
        lines.append(f"  日涨跌幅: {dc}%")
    else:
        lines.append("  日涨跌幅: N/A")
    
    lines.extend([
        f"  历史净值条数: {safe_get(data, 'nav_count', default=0)}",
        f"  最大回撤: {safe_get(data, 'max_drawdown', default=0):.2f}%",
        "", "📈 业绩基准",
        f"  {safe_get(data, 'benchmark', default='N/A')}",
    ])
    
    goal = safe_get(data, 'investment_goal')
    if goal:
        lines.extend(["", "🎯 投资目标", f"  {goal[:80]}..."])
    
    nav_df = data.get('history_nav')
    if nav_df is not None and not nav_df.empty:
        lines.extend(["", "📈 最近5天净值"])
        for _, row in nav_df.tail(5).iterrows():
            date = row.get("净值日期", "N/A")
            if hasattr(date, 'strftime'):
                date = date.strftime("%Y-%m-%d")
            lines.append(f"  {date}: {row.get('单位净值', 'N/A')} ({row.get('日增长率', 'N/A')}%)")
    
    return "\n".join(lines)


# Layer 7: 基金持仓分析

@cached(ttl_hours=24)
def get_fund_holdings_direct(code: str) -> pd.DataFrame:
    """获取基金最新持仓（从东财 F10 抓取）"""
    code = normalize_fund_code(code)
    url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {
        "type": "jjcc",
        "code": code,
        "topline": "100",
        "year": datetime.now().strftime("%Y"),
        "month": datetime.now().strftime("%m"),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://fundf10.eastmoney.com/ccmx_{code}.html",
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', class_='w782')
        if not table:
            logger.debug(f"持仓表未找到: {code}")
            return pd.DataFrame()

        rows = []
        for tr in table.find_all('tr')[1:]:
            tds = tr.find_all('td')
            if len(tds) >= 7:
                rows.append({
                    "代码": tds[1].get_text(strip=True) if len(tds) > 1 else "",
                    "名称": tds[2].get_text(strip=True) if len(tds) > 2 else "",
                    "占比": tds[6].get_text(strip=True) if len(tds) > 6 else "",
                })
        return pd.DataFrame(rows)
    except Exception as e:
        logger.warning(f"获取持仓失败 {code}: {e}")
        return pd.DataFrame()

@cached(ttl_hours=24)
def get_fund_holdings_change_direct(code: str) -> pd.DataFrame:
    """获取基金上季度持仓（用于对比变化）"""
    code = normalize_fund_code(code)
    # 自动计算上季度
    now = datetime.now()
    if now.month <= 3:
        year, month = now.year - 1, 12
    elif now.month <= 6:
        year, month = now.year, 3
    elif now.month <= 9:
        year, month = now.year, 6
    else:
        year, month = now.year, 9

    url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {
        "type": "jjcc",
        "code": code,
        "topline": "100",
        "year": str(year),
        "month": str(month),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://fundf10.eastmoney.com/ccmx_{code}.html",
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', class_='w782')
        if not table:
            return pd.DataFrame()

        rows = []
        for tr in table.find_all('tr')[1:]:
            tds = tr.find_all('td')
            if len(tds) >= 7:
                rows.append({
                    "代码": tds[1].get_text(strip=True),
                    "名称": tds[2].get_text(strip=True),
                    "占比": tds[6].get_text(strip=True),
                })
        return pd.DataFrame(rows)
    except Exception as e:
        logger.warning(f"获取上季度持仓失败 {code}: {e}")
        return pd.DataFrame()

def compare_holdings(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """对比当前和上季度持仓变化"""
    if current.empty:
        return pd.DataFrame()
    if previous.empty:
        df = current.copy()
        df["变化"] = "新增"
        return df

    merged = current.merge(previous, on="代码", how="left", suffixes=("_cur", "_prev"))

    def parse_ratio(ratio_str):
        try:
            return float(str(ratio_str).replace("%", ""))
        except (ValueError, TypeError):
            return 0.0

    def format_change(row):
        cur = parse_ratio(row.get("占比_cur", "0%"))
        prev = parse_ratio(row.get("占比_prev", "0%"))
        if prev == 0:
            return "新增"
        diff = cur - prev
        if diff > 0:
            return f"+{diff:.2f}%"
        elif diff < 0:
            return f"{diff:.2f}%"
        return "持平"

    result = pd.DataFrame({
        "代码": merged["代码"],
        "名称": merged["名称_cur"],
        "占比": merged["占比_cur"],
        "变化": merged.apply(format_change, axis=1),
    })
    return result

def get_fund_holdings(code: str, date: str = None) -> pd.DataFrame:
    """获取基金持仓（默认最新）"""
    return get_fund_holdings_direct(code)

def format_holdings_with_change(df: pd.DataFrame, top_n: int = 10) -> str:
    """格式化输出持仓变化"""
    if df.empty:
        return "暂无持仓数据"

    lines = [f"📊 前 {top_n} 大持仓", ""]
    lines.append(f"{'代码':<10} {'名称':<14} {'占比':<10} {'较上季度':<12}")
    lines.append("-" * 50)

    for _, row in df.head(top_n).iterrows():
        code = str(row.get("代码", "N/A"))[:8]
        name = str(row.get("名称", "N/A"))[:12]
        ratio = str(row.get("占比", "N/A"))
        change = str(row.get("变化", "N/A"))
        lines.append(f"{code:<10} {name:<14} {ratio:<10} {change:<12}")

    return "\n".join(lines)

# Layer 8: 基金评分系统

FUND_TYPE_KEYWORDS = {
    "主动股票型": ["股票型", "普通股票"],
    "指数型": ["指数", "ETF", "LOF", "联接"],
    "偏股混合型": ["偏股", "积极配置", "稳健配置"],
    "偏债混合型": ["偏债", "保守配置"],
    "灵活配置型": ["灵活配置", "平衡"],
    "纯债型": ["纯债", "中短债", "长债", "信用债", "利率债"],
    "可转债型": ["可转债", "转债"],
    "货币型": ["货币", "理财", "短期"],
    "FOF": ["FOF", "基金中基金"],
    "QDII": ["QDII"],
    "商品型": ["商品", "黄金", "油气"],
}

_SCORE_CONFIGS = {
    "主动股票型": {"w": (0.40, 0.20, 0.20, 0.20), "r1": [(40,5),(25,4.5),(15,4),(10,3.5),(5,3),(0,2.5),(-10,2),(-20,1.5),(-30,1)], "r3": [(25,5),(18,4.5),(12,4),(8,3.5),(4,3),(0,2.5),(-8,2),(-15,1.5),(-25,1)], "dd": [(0,5),(8,4.5),(15,4),(20,3.5),(25,3),(30,2.5),(40,2),(50,1.5)], "vol": [(0,5),(8,4.5),(15,4),(20,3.5),(25,3),(30,2.5),(35,2),(45,1.5)], "wr": [(58,5),(55,4.5),(52,4),(50,3.5),(48,3),(45,2.5),(40,2)], "nh": [(25,5),(20,4.5),(15,4),(10,3.5),(5,3),(2,2.5),(0,2)], "cal": [(3,5),(2,4.5),(1.5,4),(1,3.5),(0.5,3),(0,2.5)]},
    "指数型": {"w": (0.30, 0.25, 0.25, 0.20), "r1": [(35,5),(20,4.5),(12,4),(8,3.5),(4,3),(0,2.5),(-10,2),(-20,1.5),(-30,1)], "r3": [(20,5),(14,4.5),(10,4),(6,3.5),(3,3),(0,2.5),(-8,2),(-15,1.5),(-25,1)], "dd": [(0,5),(10,4.5),(18,4),(25,3.5),(30,3),(35,2.5),(45,2)], "vol": [(0,5),(10,4.5),(18,4),(25,3.5),(30,3),(35,2.5),(45,2)], "wr": [(55,5),(52,4.5),(49,4),(47,3.5),(45,3),(42,2.5),(38,2)], "nh": [(20,5),(15,4.5),(10,4),(7,3.5),(4,3),(2,2.5),(0,2)], "cal": [(2,5),(1.5,4.5),(1,4),(0.6,3.5),(0.3,3),(0,2.5)]},
    "偏股混合型": {"w": (0.35, 0.25, 0.20, 0.20), "r1": [(35,5),(20,4.5),(12,4),(8,3.5),(4,3),(0,2.5),(-10,2),(-20,1.5),(-30,1)], "r3": [(22,5),(15,4.5),(10,4),(6,3.5),(3,3),(0,2.5),(-8,2),(-15,1.5),(-25,1)], "dd": [(0,5),(8,4.5),(15,4),(20,3.5),(25,3),(30,2.5),(40,2),(50,1.5)], "vol": [(0,5),(8,4.5),(15,4),(20,3.5),(25,3),(30,2.5),(40,2)], "wr": [(56,5),(53,4.5),(50,4),(48,3.5),(46,3),(43,2.5),(40,2)], "nh": [(22,5),(17,4.5),(12,4),(8,3.5),(4,3),(2,2.5),(0,2)], "cal": [(2.5,5),(1.8,4.5),(1.2,4),(0.8,3.5),(0.5,3),(0,2.5)]},
    "偏债混合型": {"w": (0.25, 0.35, 0.20, 0.20), "r1": [(15,5),(10,4.5),(7,4),(5,3.5),(3,3),(1,2.5),(0,2),(-2,1.5),(-5,1)], "r3": [(12,5),(8,4.5),(6,4),(4,3.5),(2.5,3),(1,2.5),(0,2),(-2,1.5),(-5,1)], "dd": [(0,5),(3,4.5),(6,4),(10,3.5),(12,3),(15,2.5),(20,2)], "vol": [(0,5),(3,4.5),(6,4),(10,3.5),(12,3),(15,2.5),(20,2)], "wr": [(60,5),(57,4.5),(54,4),(52,3.5),(50,3),(48,2.5),(45,2)], "nh": [(30,5),(25,4.5),(20,4),(15,3.5),(10,3),(5,2.5),(0,2)], "cal": [(5,5),(3,4.5),(2,4),(1.2,3.5),(0.8,3),(0.5,2.5)]},
    "灵活配置型": {"w": (0.30, 0.30, 0.20, 0.20), "r1": [(30,5),(18,4.5),(12,4),(8,3.5),(4,3),(0,2.5),(-8,2),(-15,1.5),(-25,1)], "r3": [(20,5),(14,4.5),(10,4),(6,3.5),(3,3),(0,2.5),(-6,2),(-12,1.5),(-20,1)], "dd": [(0,5),(6,4.5),(12,4),(18,3.5),(22,3),(28,2.5),(38,2)], "vol": [(0,5),(6,4.5),(12,4),(18,3.5),(22,3),(28,2.5),(38,2)], "wr": [(57,5),(54,4.5),(51,4),(49,3.5),(47,3),(44,2.5),(40,2)], "nh": [(22,5),(17,4.5),(12,4),(8,3.5),(4,3),(2,2.5),(0,2)], "cal": [(2.5,5),(1.8,4.5),(1.2,4),(0.8,3.5),(0.5,3),(0,2.5)]},
    "纯债型": {"w": (0.25, 0.35, 0.20, 0.20), "r1": [(8,5),(6,4.5),(4.5,4),(3.5,3.5),(2.5,3),(1.5,2.5),(0.5,2),(0,1.5),(-1,1)], "r3": [(7,5),(5.5,4.5),(4,4),(3,3.5),(2,3),(1,2.5),(0.5,2),(0,1.5),(-1,1)], "dd": [(0,5),(0.5,4.5),(1,4),(1.5,3.5),(2,3),(3,2.5),(5,2)], "vol": [(0,5),(0.5,4.5),(1,4),(1.5,3.5),(2,3),(3,2.5),(5,2)], "wr": [(65,5),(62,4.5),(59,4),(57,3.5),(55,3),(52,2.5),(48,2)], "nh": [(40,5),(35,4.5),(30,4),(25,3.5),(20,3),(12,2.5),(5,2)], "cal": [(15,5),(10,4.5),(6,4),(4,3.5),(2.5,3),(1.5,2.5)]},
    "可转债型": {"w": (0.30, 0.30, 0.20, 0.20), "r1": [(20,5),(14,4.5),(10,4),(7,3.5),(4,3),(1,2.5),(-3,2),(-8,1.5),(-15,1)], "r3": [(15,5),(10,4.5),(7,4),(5,3.5),(3,3),(0,2.5),(-3,2),(-8,1.5),(-15,1)], "dd": [(0,5),(3,4.5),(6,4),(10,3.5),(15,3),(20,2.5),(25,2)], "vol": [(0,5),(3,4.5),(6,4),(10,3.5),(15,3),(20,2.5),(25,2)], "wr": [(58,5),(55,4.5),(52,4),(50,3.5),(48,3),(45,2.5),(40,2)], "nh": [(25,5),(20,4.5),(15,4),(10,3.5),(6,3),(3,2.5),(0,2)], "cal": [(3,5),(2,4.5),(1.2,4),(0.8,3.5),(0.5,3),(0,2.5)]},
    "货币型": {"w": (0.20, 0.40, 0.20, 0.20), "r1": [(3.5,5),(3,4.5),(2.5,4),(2,3.5),(1.5,3),(1,2.5),(0.5,2)], "r3": [(3.5,5),(3,4.5),(2.5,4),(2,3.5),(1.5,3),(1,2.5),(0.5,2)], "dd": [(0,5),(0.05,4.5),(0.1,4),(0.2,3.5),(0.3,3),(0.5,2.5)], "vol": [(0,5),(0.05,4.5),(0.1,4),(0.2,3.5),(0.3,3),(0.5,2.5)], "wr": [(70,5),(65,4.5),(60,4),(55,3.5),(50,3)], "nh": [(80,5),(70,4.5),(60,4),(50,3.5),(40,3)], "cal": [(20,5),(12,4.5),(8,4),(5,3.5),(3,3)]},
    "FOF": {"w": (0.30, 0.30, 0.20, 0.20), "r1": [(18,5),(12,4.5),(8,4),(5,3.5),(3,3),(0,2.5),(-4,2),(-8,1.5),(-12,1)], "r3": [(14,5),(9,4.5),(6,4),(4,3.5),(2,3),(0,2.5),(-3,2),(-6,1.5),(-10,1)], "dd": [(0,5),(5,4.5),(10,4),(15,3.5),(20,3),(25,2.5),(30,2)], "vol": [(0,5),(5,4.5),(10,4),(15,3.5),(20,3),(25,2.5),(30,2)], "wr": [(56,5),(53,4.5),(50,4),(48,3.5),(46,3),(43,2.5),(40,2)], "nh": [(20,5),(15,4.5),(10,4),(7,3.5),(4,3),(2,2.5),(0,2)], "cal": [(2,5),(1.5,4.5),(1,4),(0.6,3.5),(0.3,3),(0,2.5)]},
    "QDII": {"w": (0.35, 0.25, 0.20, 0.20), "r1": [(30,5),(20,4.5),(12,4),(8,3.5),(4,3),(-2,2.5),(-10,2),(-20,1.5),(-30,1)], "r3": [(20,5),(14,4.5),(10,4),(6,3.5),(3,3),(-2,2.5),(-8,2),(-15,1.5),(-25,1)], "dd": [(0,5),(10,4.5),(18,4),(25,3.5),(30,3),(38,2.5),(50,2)], "vol": [(0,5),(10,4.5),(18,4),(25,3.5),(30,3),(38,2.5),(50,2)], "wr": [(55,5),(52,4.5),(49,4),(47,3.5),(45,3),(42,2.5),(38,2)], "nh": [(20,5),(15,4.5),(10,4),(7,3.5),(4,3),(2,2.5),(0,2)], "cal": [(2,5),(1.5,4.5),(1,4),(0.6,3.5),(0.3,3),(0,2.5)]},
    "商品型": {"w": (0.35, 0.25, 0.20, 0.20), "r1": [(35,5),(20,4.5),(12,4),(6,3.5),(2,3),(-5,2.5),(-15,2),(-25,1.5),(-35,1)], "r3": [(22,5),(15,4.5),(10,4),(6,3.5),(2,3),(-5,2.5),(-15,2),(-25,1.5),(-35,1)], "dd": [(0,5),(10,4.5),(20,4),(28,3.5),(35,3),(45,2.5),(55,2)], "vol": [(0,5),(10,4.5),(20,4),(28,3.5),(35,3),(45,2.5),(55,2)], "wr": [(55,5),(52,4.5),(49,4),(47,3.5),(45,3),(42,2.5),(38,2)], "nh": [(20,5),(15,4.5),(10,4),(7,3.5),(4,3),(2,2.5),(0,2)], "cal": [(2,5),(1.5,4.5),(1,4),(0.6,3.5),(0.3,3),(0,2.5)]},
}

def detect_fund_type(code: str) -> str:
    """判断基金类型"""
    full_info = get_fund_full_info(code)
    fund_type = full_info.get("type", "") or get_fund_type(code) or ""
    for ftype, keywords in FUND_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in fund_type:
                return ftype
    name = get_fund_name(code) or ""
    if "指数" in name or "ETF" in name:
        return "指数型"
    if "债" in name and "可转债" not in name:
        return "纯债型"
    if "QDII" in name or "海外" in name or "全球" in name:
        return "QDII"
    return "灵活配置型"

def get_score_config(fund_type: str) -> Dict:
    """获取对应类型的评分阈值"""
    cfg = _SCORE_CONFIGS.get(fund_type, _SCORE_CONFIGS["灵活配置型"])
    weights = cfg["w"]
    return {
        "weights": {"收益": weights[0], "风险": weights[1], "性价比": weights[2], "稳定": weights[3]},
        "return_1y": cfg["r1"], "return_3y": cfg["r3"],
        "max_dd": cfg["dd"], "volatility": cfg["vol"],
        "win_rate": cfg["wr"], "new_high": cfg["nh"], "calmar": cfg["cal"],
    }

def get_fund_history_by_days(code: str, days: int = 365) -> pd.DataFrame:
    """获取基金历史净值（按天数）"""
    code = normalize_fund_code(code)
    ak = _get_akshare()
    if ak is None:
        logger.debug("akshare 未安装，无法获取历史净值")
        return pd.DataFrame()
    try:
        df = ak.fund_open_fund_info_em(symbol=code)
        if df is not None and not df.empty:
            df['净值日期'] = pd.to_datetime(df['净值日期'])
            df = df.sort_values('净值日期')
            cutoff = df['净值日期'].max() - pd.Timedelta(days=days)
            return df[df['净值日期'] >= cutoff]
        return pd.DataFrame()
    except Exception as e:
        logger.debug(f"获取历史净值失败 {code}: {e}")
        return pd.DataFrame()

def calc_score_5f(value: float, thresholds: List[tuple]) -> float:
    """5分制评分"""
    for threshold, score in thresholds:
        if value >= threshold:
            return score
    return 0.5

def format_stars(score: float) -> str:
    """分数转星标"""
    if score <= 0:
        return "☆☆☆☆☆"
    full = int(score)
    half = 1 if (score - full) >= 0.5 else 0
    return "★" * full + "☆" * half + "☆" * (5 - full - half)

def get_fund_score(code: str) -> Dict[str, Any]:
    """获取基金评分"""
    code = normalize_fund_code(code)
    name = get_fund_name(code) or code
    fund_type = detect_fund_type(code)
    config = get_score_config(fund_type)

    nav_1y = get_fund_history_by_days(code, 365)
    nav_3y = get_fund_history_by_days(code, 365 * 3)

    result = {"code": code, "name": name, "type": fund_type, "scores": {}, "total": 0.0, "grade": "", "details": {}}

    ret_1y = annual_ret = max_dd = volatility = win_rate = new_high_ratio = calmar = 0.0

    if not nav_1y.empty and len(nav_1y) > 1:
        ret_1y = (nav_1y.iloc[-1]['单位净值'] / nav_1y.iloc[0]['单位净值'] - 1) * 100

    if not nav_3y.empty and len(nav_3y) > 1:
        ret_3y = (nav_3y.iloc[-1]['单位净值'] / nav_3y.iloc[0]['单位净值'] - 1) * 100
        annual_ret = ((1 + ret_3y / 100) ** (1 / 3) - 1) * 100
        max_dd = calculate_max_drawdown(nav_3y)
        nav_vals = nav_3y['单位净值'].values
        if len(nav_vals) > 1:
            daily_returns = np.diff(nav_vals) / nav_vals[:-1]
            volatility = np.std(daily_returns) * np.sqrt(252) * 100
            win_rate = (daily_returns > 0).sum() / len(daily_returns) * 100
            cummax = np.maximum.accumulate(nav_vals)
            new_high_ratio = (nav_vals == cummax).sum() / len(nav_vals) * 100
        if max_dd > 0:
            calmar = annual_ret / max_dd

    result["details"] = {
        "近1年收益": round(ret_1y, 2), "近3年年化": round(annual_ret, 2),
        "最大回撤": round(max_dd, 2), "年化波动率": round(volatility, 2),
        "卡玛比率": round(calmar, 2), "日胜率": round(win_rate, 2),
        "创新高占比": round(new_high_ratio, 2),
    }

    score_return = (calc_score_5f(ret_1y, config["return_1y"]) + calc_score_5f(annual_ret, config["return_3y"])) / 2
    score_risk = (calc_score_5f(max_dd, config["max_dd"]) + calc_score_5f(volatility, config["volatility"])) / 2
    score_value = calc_score_5f(calmar, config["calmar"])
    score_stability = (calc_score_5f(win_rate, config["win_rate"]) + calc_score_5f(new_high_ratio, config["new_high"])) / 2

    result["scores"] = {
        "收益能力": round(score_return, 1),
        "风险控制": round(score_risk, 1),
        "性价比": round(score_value, 1),
        "稳定性": round(score_stability, 1),
    }

    w = config["weights"]
    total = score_return * w["收益"] + score_risk * w["风险"] + score_value * w["性价比"] + score_stability * w["稳定"]
    result["total"] = round(total, 2)

    t = result["total"]
    if t >= 4.5:
        result["grade"] = "⭐⭐⭐⭐⭐ 优秀"
    elif t >= 4.0:
        result["grade"] = "⭐⭐⭐⭐ 良好"
    elif t >= 3.0:
        result["grade"] = "⭐⭐⭐ 一般"
    elif t >= 2.0:
        result["grade"] = "⭐⭐ 较差"
    else:
        result["grade"] = "⭐ 不推荐"
    return result

def format_fund_score(code: str) -> str:
    """格式化输出基金评分"""
    data = get_fund_score(code)
    lines = [
        "📊 基金评分报告", "",
        "┌" + "─" * 56 + "┐",
        f"│  📋 {data['name']}（{data['code']}）{' ' * (32 - len(data['name']) - len(data['code']))}│",
        f"│  📂 基金类型：{data['type']:<43}│",
        f"│  ⭐ 综合评级：{data['grade']}（{data['total']}/5.0）{' ' * (25 - len(data['grade']))}│",
        "├" + "─" * 56 + "┤",
        "│  维度         得分    评级                                    │",
    ]
    for dim, score in data["scores"].items():
        lines.append(f"│  {dim:<10} {score:>5.1f}    {format_stars(score):<38}│")
    lines.append("├" + "─" * 56 + "┤")
    lines.append("│  详细数据                                                    │")
    for key, value in data["details"].items():
        lines.append(f"│    {key}: {round(value, 2) if isinstance(value, float) else value:<43}│")
    lines.append("└" + "─" * 56 + "┘")
    return "\n".join(lines)

def compare_fund_scores(codes: List[str]) -> str:
    """对比多只基金评分"""
    results = []
    for code in codes:
        d = get_fund_score(code)
        results.append({
            "code": code,
            "name": d["name"][:10],
            "type": d["type"],
            "total": d["total"],
            "grade": d["grade"],
            "收益": d["scores"]["收益能力"],
            "风险": d["scores"]["风险控制"],
            "性价比": d["scores"]["性价比"],
            "稳定": d["scores"]["稳定性"],
        })

    lines = [
        "📊 基金评分对比", "",
        f"{'代码':<8} {'名称':<10} {'类型':<10} {'总分':<5} {'评级':<10} {'收益':<5} {'风险':<5} {'性价比':<5} {'稳定':<5}",
        "-" * 85,
    ]
    for r in results:
        lines.append(
            f"{r['code']:<8} {r['name']:<10} {r['type']:<10} {r['total']:<5} {r['grade'][:8]:<10} "
            f"{r['收益']:<5} {r['风险']:<5} {r['性价比']:<5} {r['稳定']:<5}"
        )
    return "\n".join(lines)


# Layer 9: 基金筛选器

@cached(ttl_hours=6)
def get_all_funds_from_net_list(top_n: int = 500) -> List[Dict[str, Any]]:
    """获取净值列表前 N 条（依赖 Node.js）"""
    try:
        return _fetch_net_list()[:top_n]
    except Exception as e:
        logger.error(f"获取基金列表失败: {e}")
        return []

def filter_funds(
    keyword: str = None,
    fund_type: str = None,
    min_return: float = None,
    max_return: float = None,
    min_nav: float = None,
    max_nav: float = None,
    buyable_only: bool = False,
    top_n: int = 20,
    sort_by: str = "return",
    sort_desc: bool = True
) -> List[Dict[str, Any]]:
    """
    筛选基金
    sort_by: "return" / "nav" / "code"
    """
    all_funds = get_all_funds_from_net_list(1000)
    if not all_funds:
        return []

    filtered = []
    for fund in all_funds:
        if keyword:
            name = safe_get(fund, "NAME") or safe_get(fund, "SHORTNAME") or ""
            code = safe_get(fund, "FCODE", default="")
            if keyword.lower() not in name.lower() and keyword not in code:
                continue

        if fund_type and safe_get(fund, "FUNDTYPE") != fund_type:
            continue

        ret = safe_float(fund.get("RZDF"))
        if min_return is not None and ret < min_return:
            continue
        if max_return is not None and ret > max_return:
            continue

        nav = safe_float(fund.get("DWJZ"))
        if min_nav is not None and nav < min_nav:
            continue
        if max_nav is not None and nav > max_nav:
            continue

        if buyable_only and safe_get(fund, "ISBUY") != "1":
            continue

        filtered.append(fund)

    sort_map = {
        "return": lambda x: safe_float(x.get("RZDF")),
        "nav": lambda x: safe_float(x.get("DWJZ")),
        "code": lambda x: x.get("FCODE", ""),
    }
    filtered.sort(key=sort_map.get(sort_by, sort_map["return"]), reverse=sort_desc)
    return filtered[:top_n]

def get_fund_type_map() -> Dict[str, str]:
    """基金类型代码映射"""
    return {
        "001": "股票型", "002": "混合型", "003": "债券型",
        "004": "货币型", "005": "指数型", "006": "QDII",
        "007": "FOF", "008": "商品型",
    }

def search_funds_by_keyword(keyword: str, top_n: int = 20) -> List[Dict[str, Any]]:
    """按关键词搜索基金（直连）"""
    try:
        data = fund_get("/fundSearch", params={"m": "1", "key": keyword})
        return data.get("Datas", [])[:top_n]
    except Exception as e:
        logger.error(f"搜索基金失败: {e}")
        return []

def format_search_result(items: List[Dict[str, Any]]) -> str:
    """格式化搜索结果显示"""
    if not items:
        return "未找到符合条件的基金"
    lines = ["📊 搜索结果", "", f"{'代码':<8} {'名称':<20} {'类型':<10} {'净值':<10}", "-" * 55]
    for item in items[:20]:
        code = item.get("CODE") or item.get("FCODE", "N/A")
        name = item.get("NAME") or item.get("SHORTNAME", "N/A")
        ftype = item.get("CATEGORYDESC") or item.get("FTYPE", "N/A")
        base_info = item.get("FundBaseInfo")
        nav = base_info.get("DWJZ", "N/A") if isinstance(base_info, dict) else "N/A"
        lines.append(f"{code:<8} {name[:18]:<20} {ftype:<10} {nav}")
    return "\n".join(lines)

def format_filter_result(funds: List[Dict[str, Any]]) -> str:
    """格式化筛选结果显示"""
    if not funds:
        return "未找到符合条件的基金"
    type_map = get_fund_type_map()
    lines = ["📊 基金筛选结果", "",
             f"{'代码':<8} {'名称':<16} {'类型':<8} {'净值':<10} {'涨跌':<8} {'状态':<8}",
             "-" * 65]
    for fund in funds[:20]:
        code = safe_get(fund, "FCODE", default="N/A")
        name = safe_get(fund, "SHORTNAME", default="N/A")[:14]
        fundtype = safe_get(fund, "FUNDTYPE", default="")
        ftype = type_map.get(str(fundtype), "N/A") if fundtype else "N/A"
        nav = safe_get(fund, "DWJZ", default="N/A")
        change = safe_get(fund, "RZDF", default="N/A")
        status = "可买" if safe_get(fund, "ISBUY") == "1" else "不可买"
        lines.append(f"{code:<8} {name:<16} {ftype:<8} {str(nav):<10} {str(change):<8} {status:<8}")
    return "\n".join(lines)

# Layer 10: 基金相关性分析

def get_fund_returns(code: str, days: int = 365) -> pd.Series:
    """获取基金日收益率序列"""
    code = normalize_fund_code(code)
    try:
        nav_df = get_fund_history_by_days(code, days)
        if nav_df.empty or len(nav_df) < 2:
            return pd.Series()
        nav_df = nav_df.sort_values('净值日期')
        returns = nav_df['单位净值'].pct_change().dropna() * 100
        returns.index = nav_df.loc[returns.index, '净值日期']
        return returns
    except Exception as e:
        logger.debug(f"获取收益率失败 {code}: {e}")
        return pd.Series()

def calculate_correlation(codes: List[str], days: int = 365) -> pd.DataFrame:
    """计算多只基金收益率相关性矩阵"""
    codes = list(dict.fromkeys(codes))
    if len(codes) < 2:
        logger.warning("相关性分析至少需要2只基金")
        return pd.DataFrame()
    
    return_dict = {}
    for code in codes:
        name = get_fund_name(code) or code
        ret = get_fund_returns(code, days)
        if len(ret) >= 30:
            return_dict[name] = ret
    
    if len(return_dict) < 2:
        logger.warning("收益率数据不足，无法计算相关性")
        return pd.DataFrame()
    
    df = pd.DataFrame(return_dict).dropna()
    if len(df) < 5:
        logger.warning("对齐后数据不足，无法计算相关性")
        return pd.DataFrame()
    
    return df.corr().round(3)

def find_similar_funds(
    target_code: str,
    candidate_codes: List[str],
    days: int = 365,
    threshold: float = 0.7
) -> Dict[str, Any]:
    """找出与目标基金高度相关的基金"""
    target_name = get_fund_name(target_code) or target_code
    all_codes = list(dict.fromkeys([target_code] + candidate_codes))
    
    corr_matrix = calculate_correlation(all_codes, days)
    if corr_matrix.empty:
        return {"target": target_name, "similar": [], "uncorrelated": []}
    
    similar, uncorrelated = [], []
    for code in candidate_codes:
        name = get_fund_name(code) or code
        if name not in corr_matrix.columns:
            continue
        corr_val = corr_matrix.loc[target_name, name]
        item = {"code": code, "name": name, "correlation": corr_val}
        if abs(corr_val) >= threshold:
            similar.append(item)
        else:
            uncorrelated.append(item)
    
    similar.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    uncorrelated.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    return {"target": target_name, "similar": similar, "uncorrelated": uncorrelated}

def format_similar_funds(result: Dict[str, Any]) -> str:
    """格式化相似基金结果"""
    target = result.get("target", "未知")
    similar = result.get("similar", [])
    uncorrelated = result.get("uncorrelated", [])
    
    lines = [f"🔍 与「{target}」相关性分析", ""]
    
    if similar:
        lines.append("📈 高度相关的基金（可能重复配置）:")
        for item in similar[:10]:
            corr = item["correlation"]
            if abs(corr) >= 0.8:
                level = "🔴 非常高"
            elif abs(corr) >= 0.6:
                level = "🟠 较高"
            else:
                level = "🟡 中等"
            lines.append(f"  {item['name']} ({item['code']}): {corr:.3f} {level}")
    else:
        lines.append("📈 没有找到高度相关的基金")
    
    if uncorrelated:
        lines.append("")
        lines.append("📉 低相关的基金（可作为分散配置）:")
        for item in uncorrelated[:10]:
            lines.append(f"  {item['name']} ({item['code']}): {item['correlation']:.3f}")
    
    return "\n".join(lines)

def calculate_rolling_correlation(
    code1: str,
    code2: str,
    window: int = 60,
    days: int = 365
) -> pd.DataFrame:
    """计算两只基金的滚动相关性"""
    ret1 = get_fund_returns(code1, days)
    ret2 = get_fund_returns(code2, days)
    
    if ret1.empty or ret2.empty or len(ret1) < window or len(ret2) < window:
        return pd.DataFrame()
    
    aligned = pd.DataFrame({"ret1": ret1, "ret2": ret2}).dropna()
    if len(aligned) < window:
        return pd.DataFrame()
    
    rolling_corr = aligned["ret1"].rolling(window).corr(aligned["ret2"])
    result = pd.DataFrame({
        "date": aligned.index,
        "correlation": rolling_corr
    }).dropna()
    return result

def format_rolling_correlation(result: pd.DataFrame, name1: str, name2: str) -> str:
    """格式化滚动相关性结果"""
    if result.empty:
        return "数据不足，无法计算滚动相关性"
    
    current = result["correlation"].iloc[-1]
    mean = result["correlation"].mean()
    min_val = result["correlation"].min()
    max_val = result["correlation"].max()
    
    half = len(result) // 2
    first_half = result["correlation"].iloc[:half].mean()
    second_half = result["correlation"].iloc[half:].mean()
    
    if second_half - first_half > 0.1:
        trend = "📈 上升趋势（两只基金走势趋于同步）"
    elif second_half - first_half < -0.1:
        trend = "📉 下降趋势（两只基金走势趋于分化）"
    else:
        trend = "➡️ 相对稳定（相关性变化不大）"
    
    lines = [
        f"📊 {name1} vs {name2} 滚动相关性分析",
        "",
        f"  当前相关性: {current:.3f}",
        f"  平均相关性: {mean:.3f}",
        f"  最高: {max_val:.3f} | 最低: {min_val:.3f}",
        f"  趋势判断: {trend}",
        "",
        "📈 最近10个交易日的滚动相关性:",
    ]
    
    for _, row in result.tail(10).iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        corr = row["correlation"]
        if abs(corr) >= 0.7:
            marker = "🔴"
        elif abs(corr) >= 0.5:
            marker = "🟠"
        elif abs(corr) >= 0.3:
            marker = "🟡"
        else:
            marker = "🟢"
        lines.append(f"  {date_str}: {marker} {corr:.3f}")
    
    return "\n".join(lines)

def find_alternative_funds(
    target_code: str,
    candidate_codes: List[str],
    days: int = 365,
    max_correlation: float = 0.4,
    min_return_diff: float = 5.0
) -> Dict[str, Any]:
    """寻找与目标基金低相关且有收益差异的替代基金"""
    target_name = get_fund_name(target_code) or target_code
    
    target_ret = get_fund_returns(target_code, days)
    if target_ret.empty:
        return {"target": target_name, "alternatives": [], "message": "目标基金数据不足"}
    
    target_total_return = target_ret.sum()
    alternatives = []
    
    for code in candidate_codes:
        if code == target_code:
            continue
        
        name = get_fund_name(code) or code
        cand_ret = get_fund_returns(code, days)
        if cand_ret.empty or len(cand_ret) < 30:
            continue
        
        aligned = pd.DataFrame({"target": target_ret, "cand": cand_ret}).dropna()
        if len(aligned) < 30:
            continue
        
        corr = aligned["target"].corr(aligned["cand"])
        if abs(corr) > max_correlation:
            continue
        
        cand_total_return = cand_ret.sum()
        return_diff = cand_total_return - target_total_return
        if abs(return_diff) < min_return_diff:
            continue
        
        target_vol = target_ret.std()
        cand_vol = cand_ret.std()
        
        alternatives.append({
            "code": code,
            "name": name,
            "correlation": corr,
            "return_diff": return_diff,
            "target_return": target_total_return,
            "cand_return": cand_total_return,
            "vol_ratio": cand_vol / target_vol if target_vol > 0 else 1,
            "common_days": len(aligned)
        })
    
    alternatives.sort(key=lambda x: abs(x["correlation"]))
    return {
        "target": target_name,
        "target_code": target_code,
        "alternatives": alternatives,
        "total_candidates": len(candidate_codes)
    }

def format_alternatives(result: Dict[str, Any]) -> str:
    """格式化替代基金推荐"""
    target = result.get("target", "未知")
    target_code = result.get("target_code", "")
    alts = result.get("alternatives", [])
    total = result.get("total_candidates", 0)
    
    if not alts:
        return f"🔍 没有找到适合替代「{target}」的基金\n\n💡 提示: 可以尝试扩大候选列表或调整参数"
    
    lines = [
        f"🔍 替代基金推荐: {target} ({target_code})",
        "",
        f"  共筛选 {total} 只候选基金，找到 {len(alts)} 只适合替代的基金",
        "",
        "📊 推荐列表（相关性越低，分散效果越好）:",
        "",
        f"{'代码':<8} {'名称':<16} {'相关性':<8} {'收益差':<10} {'波动比':<8}",
        "-" * 60
    ]
    
    for alt in alts[:10]:
        corr = alt["correlation"]
        ret_diff = alt["return_diff"]
        vol_ratio = alt["vol_ratio"]
        
        if abs(corr) < 0.2:
            level = "⭐ 极佳"
        elif abs(corr) < 0.3:
            level = "⭐ 良好"
        else:
            level = "⭐ 可用"
        
        ret_sign = f"+{ret_diff:.1f}%" if ret_diff > 0 else f"{ret_diff:.1f}%"
        lines.append(
            f"{alt['code']:<8} "
            f"{alt['name'][:14]:<16} "
            f"{corr:.3f}    "
            f"{ret_sign:<10} "
            f"{vol_ratio:<8.2f} "
            f"{level}"
        )
    
    lines.append("")
    lines.append("💡 说明:")
    lines.append("  · 相关性: 越低越好，< 0.3 为佳")
    lines.append("  · 收益差: 正数表示替代品收益更高")
    lines.append("  · 波动比: > 1 表示波动更大，< 1 表示波动更小")
    return "\n".join(lines)


# Layer 11: 定投收益计算

def _generate_buy_dates(
    nav_df: pd.DataFrame,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    frequency: str = "monthly",
    day_of_month: int = 1,
    day_of_week: int = 1
) -> List[pd.Timestamp]:
    """生成定投买入日期列表"""
    if start_date:
        start = pd.to_datetime(start_date)
        nav_df = nav_df[nav_df['净值日期'] >= start]
    if end_date:
        end = pd.to_datetime(end_date)
        nav_df = nav_df[nav_df['净值日期'] <= end]
    
    if nav_df.empty:
        return []
    
    nav_df = nav_df.sort_values('净值日期').reset_index(drop=True)
    start = nav_df['净值日期'].min()
    end = nav_df['净值日期'].max()
    
    buy_dates = []
    current = start
    
    if frequency == "monthly":
        while current <= end:
            try:
                buy_date = current.replace(day=day_of_month)
            except ValueError:
                next_month = current.replace(day=28) + pd.Timedelta(days=4)
                buy_date = next_month - pd.Timedelta(days=next_month.day)
            
            if buy_date < current:
                if current.month == 12:
                    buy_date = current.replace(year=current.year + 1, month=1, day=day_of_month)
                else:
                    buy_date = current.replace(month=current.month + 1, day=day_of_month)
            
            if buy_date > end:
                break
            
            closest_row = nav_df.iloc[(nav_df['净值日期'] - buy_date).abs().argsort()[:1]]
            closest_date = closest_row['净值日期'].iloc[0]
            if closest_date not in buy_dates:
                buy_dates.append(closest_date)
            
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1, day=1)
            else:
                current = current.replace(month=current.month + 1, day=1)
    
    elif frequency == "weekly":
        while current <= end:
            days_ahead = day_of_week - current.weekday()
            if days_ahead < 0:
                days_ahead += 7
            buy_date = current + pd.Timedelta(days=days_ahead)
            if buy_date > end:
                break
            closest_row = nav_df.iloc[(nav_df['净值日期'] - buy_date).abs().argsort()[:1]]
            closest_date = closest_row['净值日期'].iloc[0]
            if closest_date not in buy_dates:
                buy_dates.append(closest_date)
            current = current + pd.Timedelta(days=7)
    
    elif frequency == "biweekly":
        count = 0
        while current <= end:
            if count % 2 == 0:
                days_ahead = day_of_week - current.weekday()
                if days_ahead < 0:
                    days_ahead += 7
                buy_date = current + pd.Timedelta(days=days_ahead)
                if buy_date <= end:
                    closest_row = nav_df.iloc[(nav_df['净值日期'] - buy_date).abs().argsort()[:1]]
                    closest_date = closest_row['净值日期'].iloc[0]
                    if closest_date not in buy_dates:
                        buy_dates.append(closest_date)
            current = current + pd.Timedelta(days=7)
            count += 1
    
    elif frequency == "quarterly":
        while current <= end:
            try:
                buy_date = current.replace(day=day_of_month)
            except ValueError:
                next_month = current.replace(day=28) + pd.Timedelta(days=4)
                buy_date = next_month - pd.Timedelta(days=next_month.day)
            
            if buy_date < current:
                if current.month > 9:
                    buy_date = current.replace(year=current.year + 1, month=(current.month - 9), day=day_of_month)
                else:
                    buy_date = current.replace(month=current.month + 3, day=day_of_month)
            
            if buy_date > end:
                break
            
            closest_row = nav_df.iloc[(nav_df['净值日期'] - buy_date).abs().argsort()[:1]]
            closest_date = closest_row['净值日期'].iloc[0]
            if closest_date not in buy_dates:
                buy_dates.append(closest_date)
            
            if current.month > 9:
                current = current.replace(year=current.year + 1, month=(current.month - 9), day=1)
            else:
                current = current.replace(month=current.month + 3, day=1)
    
    else:
        logger.warning(f"不支持的定投频率: {frequency}，使用月度定投")
        return _generate_buy_dates(nav_df, start_date, end_date, "monthly", day_of_month)
    
    return buy_dates

def calculate_drip(
    code: str,
    amount: float = 1000.0,
    start_date: str = None,
    end_date: str = None,
    frequency: str = "monthly",
    day_of_month: int = 1,
    day_of_week: int = 1,
    fee_rate: float = 0.0015
) -> Dict[str, Any]:
    """
    计算定投收益
    frequency: monthly / weekly / biweekly / quarterly
    """
    code = normalize_fund_code(code)
    
    if amount <= 0:
        return {"error": f"定投金额必须大于0，当前值: {amount}"}
    
    valid_frequencies = ["monthly", "weekly", "biweekly", "quarterly"]
    if frequency not in valid_frequencies:
        return {"error": f"不支持的定投频率: {frequency}，支持: {', '.join(valid_frequencies)}"}
    
    nav_df = get_fund_history_by_days(code, 365 * 5)
    if nav_df.empty:
        return {"error": "无法获取基金历史净值数据"}
    
    buy_dates = _generate_buy_dates(nav_df, start_date, end_date, frequency, day_of_month, day_of_week)
    if not buy_dates:
        return {"error": "没有生成定投日期，请检查日期范围或定投参数"}
    
    nav_df = nav_df.sort_values('净值日期').reset_index(drop=True)
    shares, total_cost = 0.0, 0.0
    records = []
    
    logger.info(f"开始定投模拟: {code}, 共 {len(buy_dates)} 次")
    
    for buy_date in buy_dates:
        nav_row = nav_df[nav_df['净值日期'] == buy_date]
        if nav_row.empty:
            continue
        nav = nav_row.iloc[0]['单位净值']
        actual_amount = amount * (1 - fee_rate)
        shares_bought = actual_amount / nav
        shares += shares_bought
        total_cost += amount
        records.append({
            "date": buy_date, "nav": nav, "amount": amount,
            "shares": shares_bought, "cumulative_shares": shares,
            "cumulative_cost": total_cost
        })
    
    if not records:
        return {"error": "没有成功执行任何定投"}
    
    latest_date = nav_df['净值日期'].max()
    latest_nav = nav_df[nav_df['净值日期'] == latest_date].iloc[0]['单位净值']
    final_value = shares * latest_nav
    
    lump_sum_amount = total_cost
    lump_sum_shares = lump_sum_amount / nav_df.iloc[0]['单位净值']
    lump_sum_value = lump_sum_shares * latest_nav
    
    total_profit = final_value - total_cost
    total_return = (total_profit / total_cost) * 100 if total_cost > 0 else 0
    lump_sum_profit = lump_sum_value - lump_sum_amount
    lump_sum_return = (lump_sum_profit / lump_sum_amount) * 100 if lump_sum_amount > 0 else 0
    
    days = (latest_date - nav_df['净值日期'].min()).days
    years = days / 365.25
    annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100 if years > 0 else 0
    
    logger.info(f"定投模拟完成: 总投入 {total_cost:.2f}, 市值 {final_value:.2f}, 收益率 {total_return:.2f}%")
    
    return {
        "code": code,
        "name": get_fund_name(code) or code,
        "total_cost": round(total_cost, 2),
        "final_value": round(final_value, 2),
        "total_profit": round(total_profit, 2),
        "total_return": round(total_return, 2),
        "annual_return": round(annual_return, 2),
        "total_shares": round(shares, 4),
        "latest_nav": latest_nav,
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "num_investments": len(records),
        "lump_sum_cost": round(lump_sum_amount, 2),
        "lump_sum_value": round(lump_sum_value, 2),
        "lump_sum_profit": round(lump_sum_profit, 2),
        "lump_sum_return": round(lump_sum_return, 2),
        "records": records,
        "start_date": records[0]["date"].strftime("%Y-%m-%d"),
        "end_date": latest_date.strftime("%Y-%m-%d"),
        "frequency": frequency,
        "amount": amount,
        "fee_rate": fee_rate
    }

def format_drip_report(result: Dict[str, Any]) -> str:
    """格式化定投报告"""
    if "error" in result:
        return f"❌ {result['error']}"
    
    lines = [
        "📊 定投收益分析报告", "",
        "📋 基本信息",
        f"  基金: {result['name']} ({result['code']})",
        f"  定投周期: {result['frequency']}",
        f"  每期金额: {result['amount']:.2f} 元",
        f"  申购费率: {result.get('fee_rate', 0.0015) * 100:.2f}%",
        f"  定投次数: {result['num_investments']} 次",
        f"  投资区间: {result['start_date']} → {result['end_date']}",
        "",
        "💰 定投结果",
        f"  总投入: {result['total_cost']:.2f} 元",
        f"  最终市值: {result['final_value']:.2f} 元",
        f"  总收益: {result['total_profit']:.2f} 元",
        f"  总收益率: {result['total_return']:.2f}%",
        f"  年化收益率: {result['annual_return']:.2f}%",
        "",
        "📈 对比一次性投入",
        f"  一次性投入: {result['lump_sum_cost']:.2f} 元",
        f"  最终市值: {result['lump_sum_value']:.2f} 元",
        f"  收益率: {result['lump_sum_return']:.2f}%",
        "",
        f"📌 最新净值: {result['latest_nav']:.4f} ({result['latest_date']})",
    ]
    
    diff = result['total_return'] - result['lump_sum_return']
    if diff > 5:
        lines.append(f"✅ 定投比一次性投入高出 {diff:.2f}%，定投效果更好")
    elif diff < -5:
        lines.append(f"⚠️ 一次性投入比定投高出 {abs(diff):.2f}%，单笔买入更优")
    else:
        lines.append(f"➡️ 定投与一次性投入差异不大（{diff:.2f}%），两种方式均可")
    
    lines.extend(["", "📋 最近10次定投记录:"])
    lines.append(f"{'日期':<12} {'净值':<10} {'投入':<10} {'累计份额':<12}")
    lines.append("-" * 48)
    
    for rec in result['records'][-10:]:
        lines.append(
            f"{rec['date'].strftime('%Y-%m-%d'):<12} "
            f"{rec['nav']:<10.4f} "
            f"{rec['amount']:<10.2f} "
            f"{rec['cumulative_shares']:<12.4f}"
        )
    return "\n".join(lines)

def compare_drip_strategies(
    code: str,
    amounts: List[float] = [500, 1000, 2000],
    start_date: str = None,
    end_date: str = None,
    frequency: str = "monthly"
) -> str:
    """对比不同定投金额的策略"""
    results = []
    for amt in amounts:
        result = calculate_drip(code, amount=amt, start_date=start_date, end_date=end_date, frequency=frequency)
        if "error" not in result:
            results.append(result)
    
    if not results:
        return "无法获取数据"
    
    lines = [
        f"📊 {results[0]['name']} 不同定投金额对比",
        "",
        f"  定投频率: {frequency}",
        f"  投资区间: {results[0]['start_date']} → {results[0]['end_date']}",
        "",
        f"{'每期金额':<10} {'总投入':<12} {'最终市值':<12} {'总收益':<12} {'收益率':<10} {'年化':<10}",
        "-" * 70
    ]
    
    for r in results:
        lines.append(
            f"{r['amount']:<10.0f} "
            f"{r['total_cost']:<12.2f} "
            f"{r['final_value']:<12.2f} "
            f"{r['total_profit']:<12.2f} "
            f"{r['total_return']:<10.2f}% "
            f"{r['annual_return']:<10.2f}%"
        )
    
    if len(results) > 1:
        best = max(results, key=lambda x: x['total_return'])
        worst = min(results, key=lambda x: x['total_return'])
        lines.append("")
        lines.append(f"🏆 最佳策略: 每期 {best['amount']:.0f} 元 (收益率 {best['total_return']:.2f}%)")
        lines.append(f"📉 最差策略: 每期 {worst['amount']:.0f} 元 (收益率 {worst['total_return']:.2f}%)")
    
    return "\n".join(lines)


# 统一门面类

class FundToolkit:
    """基金工具包统一入口"""

    def __init__(self, config: Optional[FundToolkitConfig] = None):
        if config:
            set_config(config)
        self._config = get_config()

    @property
    def config(self) -> FundToolkitConfig:
        return self._config

    # 数据层
    def search(self, keyword: str) -> List[Dict[str, Any]]:
        return search_fund(keyword)

    def get_fund(self, code: str) -> Dict[str, Any]:
        return get_fund_basic_info(code)

    def get_name(self, code: str) -> Optional[str]:
        return get_fund_name(code)

    def get_type(self, code: str) -> Optional[str]:
        return get_fund_type(code)

    def get_manager(self, code: str) -> Optional[str]:
        return get_fund_manager(code)

    def get_company(self, code: str) -> Optional[str]:
        return get_fund_company(code)

    def get_net_value(self, code: str) -> Optional[Dict[str, Any]]:
        return get_fund_net_value(code)

    def get_companies(self) -> List[Dict[str, Any]]:
        return get_company_list()

    def search_company(self, keyword: str) -> List[Dict[str, Any]]:
        return search_company(keyword)

    def get_top_companies(self, top_n: int = 10) -> List[Dict[str, Any]]:
        return get_top_companies_by_fund_count(top_n)

    def get_latest_net(self, code: str) -> Optional[Dict[str, Any]]:
        return get_latest_net_value(code)

    def get_net_list(self, top_n: int = 20) -> List[Dict[str, Any]]:
        return get_net_value_list(top_n)

    def get_themes(self) -> List[Dict[str, Any]]:
        return get_fund_themes()

    def search_theme(self, keyword: str) -> List[Dict[str, Any]]:
        return search_theme(keyword)

    def get_full_info(self, code: str) -> Dict[str, Any]:
        return get_fund_full_info(code)

    def get_history_nav(self, code: str, days: int = 30) -> pd.DataFrame:
        return get_fund_history_nav(code, days)

    def get_nav_series(self, code: str, days: int = 365) -> pd.Series:
        return get_fund_nav_series(code, days)

    def quick_analysis(self, code: str) -> Dict[str, Any]:
        return get_fund_analysis(code)

    def full_analysis(self, code: str) -> Dict[str, Any]:
        return get_full_analysis(code)

    def compare(self, codes: List[str]) -> str:
        return compare_funds(codes)

    def get_holdings(self, code: str) -> pd.DataFrame:
        return get_fund_holdings(code)

    def get_score(self, code: str) -> Dict[str, Any]:
        return get_fund_score(code)

    def compare_scores(self, codes: List[str]) -> str:
        return compare_fund_scores(codes)

    def filter_funds(self, **kwargs) -> List[Dict[str, Any]]:
        return filter_funds(**kwargs)

    def get_returns(self, code: str, days: int = 365) -> pd.Series:
        return get_fund_returns(code, days)

    def get_correlation(self, codes: List[str], days: int = 365) -> pd.DataFrame:
        return calculate_correlation(codes, days)

    def find_similar(self, target: str, candidates: List[str], **kwargs) -> Dict[str, Any]:
        return find_similar_funds(target, candidates, **kwargs)

    def find_alternatives(self, target: str, candidates: List[str], **kwargs) -> Dict[str, Any]:
        return find_alternative_funds(target, candidates, **kwargs)

    def drip(self, code: str, **kwargs) -> Dict[str, Any]:
        return calculate_drip(code, **kwargs)

    def compare_drip(self, code: str, **kwargs) -> str:
        return compare_drip_strategies(code, **kwargs)

    def get_max_drawdown(self, code: str, days: int = 365) -> float:
        df = get_fund_history_nav(code, days)
        return calculate_max_drawdown(df)

    # 决策层
    def suggest(self, risk_level: str, amount: float = 10000) -> str:
        from SKILL_FUNDADVISOR import quick_suggestion
        return quick_suggestion(risk_level, amount)

    def suggest_conservative(self, amount: float = 10000) -> str:
        from SKILL_FUNDADVISOR import suggest_conservative
        return suggest_conservative(amount)

    def suggest_balanced(self, amount: float = 10000) -> str:
        from SKILL_FUNDADVISOR import suggest_balanced
        return suggest_balanced(amount)

    def suggest_aggressive(self, amount: float = 10000) -> str:
        from SKILL_FUNDADVISOR import suggest_aggressive
        return suggest_aggressive(amount)

    def recommend(self, risk_level: str, **kwargs) -> List:
        from SKILL_FUNDADVISOR import recommend_funds, InvestorRisk
        return recommend_funds(InvestorRisk(risk_level.upper()), **kwargs)

    def build_portfolio(self, risk_level: str, fund_codes: List[str], **kwargs):
        from SKILL_FUNDADVISOR import build_portfolio, InvestorRisk
        return build_portfolio(InvestorRisk(risk_level.upper()), fund_codes, **kwargs)

    def compare_risk(self, codes: List[str]) -> str:
        from SKILL_FUNDADVISOR import compare_risk_levels
        return compare_risk_levels(codes)

    # 可视化层
    def generate_report(self, code: str, output_path: str = None) -> str:
        from SKILL_FUNDCOUNT_VIS import generate_fund_html_report
        return generate_fund_html_report(code, output_path=output_path)

    def generate_compare_report(self, codes: List[str], output_path: str = None) -> str:
        from SKILL_FUNDCOUNT_VIS import generate_funds_compare_html
        return generate_funds_compare_html(codes, output_path=output_path) 

    # 工具
    def clear_cache(self, pattern: Optional[str] = None) -> int:
        return clear_cache(pattern)

    def test_connection(self, verbose: bool = False) -> bool:
        return test_connection(verbose)

    def set_log_level(self, level: Union[str, int]) -> None:
        set_log_level(level)
