"""
fund_skill.py — 基金全栈数据工具包（Skill 自包含单文件版）V2.0.0

设计目标
--------
1. 零本地服务：不再需要 Node.js / TiantianFundApi（原 base_url 依赖已完全移除）
2. 零第三方数据源库：不再需要 akshare
3. 零第三方依赖：只用 Python 标准库（urllib 做 HTTP、statistics 做统计、
   纯 Python 算皮尔逊相关与 XIRR），不需要 requests / pandas / numpy。
   任何 Python 3.8+ 解释器都能直接跑，无需 pip install。

模块名特意叫 fund_skill 而不是 fund_toolkit：后者可能已被 site-packages 里的
旧版本（V1.3，评分与复权都有 bug）占用，同名会导致 `import fund_toolkit`
静默拿到旧版并给出错误结果。改名后不可能再被抢占。

数据源（全部为天天基金/东方财富公开接口，均免 token，实测可用）
--------------------------------------------------------------
  搜索          fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx
  历史净值      fund.eastmoney.com/pingzhongdata/{code}.js   （单位净值/累计净值/分红）
  全量类型表    fund.eastmoney.com/js/fundcode_search.js     （28065 只 代码/简称/类型）
  全量排行      fund.eastmoney.com/data/rankhandler.aspx     （20580 行 × 25 字段）
  基金公司      fundmobapi.eastmoney.com/FundMApi/FundCompanyBaseList.ashx （215 家）
  大数据榜单    appconfig2.1234567.com.cn/config/BigDataList （14 个榜单，替代主题榜单）
  持仓          fundf10.eastmoney.com/FundArchivesDatas.aspx （页面含两张表=本季/上季）
  指数K线       push2his.eastmoney.com/api/qt/stock/kline/get （报告基准）

已按代码审查结论修正的问题
--------------------------
  · 评分“风险控制”维度阈值方向写反导致恒为 5.0        -> calc_score_5f(higher_is_better)
  · 全部指标基于未复权单位净值，分红日被算成暴跌        -> 复权序列（累计净值差分法）
  · 货币基金类型识别失效、数据必然缺失、C1 恒空         -> 货币基金独立口径
  · 指数基金被判为主动股票型（dict 顺序）              -> 有序优先级规则
  · “近3年年化”硬编码 1/3，新基金被低估                -> 按真实日历跨度年化
  · 不存在/近似代码静默返回别的标的                     -> 精确命中校验
  · 定投估值日与一次性基准不受 start/end 约束           -> 区间裁剪
  · 定投“年化”非货币加权                               -> XIRR
  · 定投买入日跨月吸附、去重丢单、月末崩溃              -> 计划日→可交易日顺延映射
  · 定投忽略分红与赎回费                               -> 复权估值 + 分档赎回费
  · 持仓“较上季度”取到同一张表                          -> 取两张表分别对比
  · HTML 报告基准线按行数截取导致错位数月               -> 日历天截取 + 日期对齐
  · 基金名称/类型裸拼 HTML/JS                          -> 转义
  · ECharts setOption 合并残留上一周期曲线              -> 整图替换
  · 缓存用 pickle + 跨进程不稳定 key + 空结果缓存       -> JSON 缓存 + 稳定 key + 可缓存性判定
  · 数据源一次性故障即永久熔断                          -> 冷却式半开熔断

用法
----
    import sys
    sys.path.insert(0, "<本文件所在目录>")
    from fund_skill import FundToolkit

    tk = FundToolkit()
    tk.search("易方达蓝筹")
    tk.get_score("110011")
    tk.drip("110011", amount=1000, start_date="2023-01-01", end_date="2023-12-31")
    tk.suggest("C3", amount=10000)
    tk.generate_report("110011", "report.html")

    自检：print(fund_skill.__file__) 应指向本文件，而不是 site-packages 里的旧包。
"""

from __future__ import annotations

import calendar
import gzip
import hashlib
import html as _html
import json
import logging
import math
import os
import random
import re
import socket
import ssl
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__version__ = "2.0.0"

logger = logging.getLogger("fund_toolkit")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.WARNING)


def set_log_level(level) -> None:
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.WARNING)
    logger.setLevel(level)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(float(raw.strip()))
    except ValueError:
        logger.warning("环境变量 %s=%r 不是整数，回退默认值 %s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        logger.warning("环境变量 %s=%r 不是数字，回退默认值 %s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off", ""):
        return False
    logger.warning("环境变量 %s=%r 无法识别，回退默认值 %s", name, raw, default)
    return default


@dataclass
class FundToolkitConfig:
    """运行配置。注意：已无 base_url / Node.js 服务依赖。"""

    timeout: int = field(default_factory=lambda: _env_int("FUND_TIMEOUT", 20))
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
    verify_ssl: bool = field(default_factory=lambda: _env_bool("FUND_VERIFY_SSL", True))
    min_interval: float = field(default_factory=lambda: _env_float("FUND_MIN_INTERVAL", 0.3))
    enable_rate_limit: bool = field(default_factory=lambda: _env_bool("FUND_ENABLE_RATE_LIMIT", True))
    cache_enabled: bool = field(default_factory=lambda: _env_bool("FUND_CACHE_ENABLED", True))
    cache_ttl_hours: float = field(default_factory=lambda: _env_float("FUND_CACHE_TTL", 12))
    cache_dir: Optional[str] = None
    retries: int = field(default_factory=lambda: _env_int("FUND_RETRIES", 2))
    source_cooldown: float = field(default_factory=lambda: _env_float("FUND_SOURCE_COOLDOWN", 300))

    def __post_init__(self):
        if self.cache_dir is None:
            # 特意与旧版 fund_toolkit 的 ~/.fund_toolkit_cache 分开：
            # 旧版写的是 .pkl、本版写 .json，混在一个目录里只会让人分不清谁是谁。
            self.cache_dir = str(Path.home() / ".fund_skill_cache")
        try:
            Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
        except OSError as e:                                  # 只读环境不应导致 import 失败
            logger.warning("缓存目录不可用 %s: %s（已关闭缓存）", self.cache_dir, e)
            self.cache_enabled = False


_current_config = FundToolkitConfig()


def get_config() -> FundToolkitConfig:
    return _current_config


def set_config(config: FundToolkitConfig) -> None:
    global _current_config
    _current_config = config
    _MEMO.clear()                          # 配置变更后失效进程内记忆


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class FundToolkitError(Exception):
    """本工具包所有异常的基类"""


class FundConnectionError(FundToolkitError):
    """网络/上游接口不可用"""


class FundNotFoundError(FundToolkitError):
    """基金不存在（或搜索只返回近似结果）"""


class FundDataError(FundToolkitError):
    """上游返回了无法解析的数据"""


# ---------------------------------------------------------------------------
# HTTP 层：标准库 urllib 实现（不依赖 requests）
#   限流（带锁）+ 异常统一包装 + 重试 + 按数据源冷却熔断
# ---------------------------------------------------------------------------

_RATE_LOCK = threading.Lock()
_LAST_CALL = 0.0
_SOURCE_DOWN_UNTIL: Dict[str, float] = {}

UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148"
)


class _Response:
    """urllib 的响应包装，接口形状对齐 requests（.text/.json/.status_code/.encoding）。"""

    __slots__ = ("status_code", "content", "url", "_headers", "encoding")

    def __init__(self, status_code: int, content: bytes, url: str, headers=None):
        self.status_code = status_code
        self.content = content
        self.url = url
        self._headers = headers or {}
        self.encoding: Optional[str] = None

    @property
    def apparent_encoding(self) -> Optional[str]:
        ctype = ""
        try:
            ctype = self._headers.get("Content-Type", "") or ""
        except AttributeError:
            pass
        m = re.search(r"charset=['\"]?([\w\-]+)", ctype, re.I)
        return m.group(1) if m else None

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or self.apparent_encoding or "utf-8",
                                   errors="replace")

    def json(self):
        return json.loads(self.text)


def _build_url(url: str, params: Optional[Dict[str, Any]]) -> str:
    if not params:
        return url
    clean = {k: v for k, v in params.items() if v is not None}
    query = urllib.parse.urlencode(clean)
    return f"{url}{'&' if '?' in url else '?'}{query}"


def _ssl_context():
    config = get_config()
    if config.verify_ssl:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _throttle() -> None:
    """判定 → sleep → 记账 放在同一把锁里，保证多线程下间隔有效。"""
    config = get_config()
    if not config.enable_rate_limit:
        return
    global _LAST_CALL
    with _RATE_LOCK:
        wait = config.min_interval - (time.time() - _LAST_CALL)
        if wait > 0:
            time.sleep(wait + random.uniform(0.02, 0.08))
        _LAST_CALL = time.time()


def _http(url: str, *, params=None, data=None, headers=None, method: str = "GET",
          timeout: Optional[int] = None, source: str = "") -> _Response:
    """唯一出口：统一限流、异常包装、重试、按数据源冷却。"""
    config = get_config()
    if source:
        until = _SOURCE_DOWN_UNTIL.get(source, 0.0)
        if until and time.time() < until:
            raise FundConnectionError(f"数据源 {source} 冷却中（{until - time.time():.0f}s 后重试）")
        _SOURCE_DOWN_UNTIL.pop(source, None)

    merged = {"User-Agent": config.user_agent, "Accept": "*/*"}
    if headers:
        merged.update(headers)
    body = urllib.parse.urlencode(data).encode("utf-8") if data else None
    if body is not None:
        merged.setdefault("Content-Type", "application/x-www-form-urlencoded")
    target = _build_url(url, params)
    wait = timeout or config.timeout

    last_exc: Optional[Exception] = None
    for attempt in range(config.retries + 1):
        _throttle()
        try:
            req = urllib.request.Request(target, data=body, headers=merged, method=method)
            with urllib.request.urlopen(req, timeout=wait, context=_ssl_context()) as resp:
                raw = resp.read()
                status = getattr(resp, "status", 200) or 200
                hdrs = dict(resp.headers.items()) if resp.headers else {}
            if hdrs.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            out = _Response(status, raw, target, hdrs)
            if status != 200:
                raise FundConnectionError(f"HTTP {status}: {target}")
            return out
        except urllib.error.HTTPError as e:
            # 4xx/5xx 也返回响应体，交给调用方按 status_code 处理
            try:
                raw = e.read()
            except Exception:
                raw = b""
            hdrs = dict(e.headers.items()) if e.headers else {}
            if hdrs.get("Content-Encoding", "").lower() == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
            return _Response(e.code, raw, target, hdrs)
        except (urllib.error.URLError, OSError, ValueError) as e:
            last_exc = e
            if attempt < config.retries:
                time.sleep(0.4 * (attempt + 1))
    if source:
        _SOURCE_DOWN_UNTIL[source] = time.time() + config.source_cooldown
        logger.warning("数据源 %s 冷却 %.0fs：%s", source, config.source_cooldown, last_exc)
    raise FundConnectionError(f"请求失败: {url} => {last_exc}")


def reset_source_status(source: Optional[str] = None) -> None:
    """手动恢复被冷却的数据源（诊断用）。"""
    if source is None:
        _SOURCE_DOWN_UNTIL.clear()
    else:
        _SOURCE_DOWN_UNTIL.pop(source, None)


def test_connection(verbose: bool = False) -> bool:
    """连通性自检：不再有“本地服务”可测，改为测 4 个真实上游。"""
    checks = [
        ("搜索接口", lambda: _search_raw("110011")),
        ("净值序列", lambda: _pingzhongdata("110011")),
        ("类型表", lambda: get_fund_type_table()),
        ("公司列表", lambda: get_company_list()),
    ]
    ok_all = True
    for name, fn in checks:
        try:
            fn()
            if verbose:
                print(f"✅ {name}")
        except Exception as e:
            ok_all = False
            if verbose:
                print(f"❌ {name}: {e}")
    if ok_all:
        reset_source_status()
    return ok_all


# ---------------------------------------------------------------------------
# 缓存：JSON 格式（不用 pickle）、稳定 key、只缓存有效结果、原子写
# ---------------------------------------------------------------------------

def _cache_path(key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return Path(get_config().cache_dir) / f"{digest}.json"


# 进程内记忆：key -> (写入时间, 值)
_MEMO: Dict[str, Tuple[float, Any]] = {}


def _cacheable(value: Any) -> bool:
    """空结果一律不缓存：否则一次网络故障会把它固化一整天。"""
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict, set, str)):
        return len(value) > 0
    return True


def _cached(ttl_hours: Optional[float] = None, key_prefix: str = ""):
    def decorator(func):
        def wrapper(*args, **kwargs):
            config = get_config()
            if not config.cache_enabled:
                return func(*args, **kwargs)
            parts = [__version__, key_prefix or func.__name__]
            parts += [repr(a) for a in args]
            parts += [f"{k}={v!r}" for k, v in sorted(kwargs.items())]
            key = "|".join(parts)
            ttl = config.cache_ttl_hours if ttl_hours is None else ttl_hours

            # 进程内记忆：像类型表（2.4MB / 2.8 万条）这种大表会被 filter_funds
            # 之类的循环按行调用，只靠磁盘缓存会导致每次调用都重新读盘+解析
            # —— 实测把 2 万行的筛选拖到 480 秒。
            memo = _MEMO.get(key)
            if memo is not None and time.time() - memo[0] < ttl * 3600:
                return memo[1]

            path = _cache_path(key)
            if path.exists():
                try:
                    if time.time() - path.stat().st_mtime < ttl * 3600:
                        with open(path, "r", encoding="utf-8") as f:
                            payload = json.load(f)
                        if isinstance(payload, dict) and payload.get("version") == __version__:
                            _MEMO[key] = (time.time(), payload["value"])
                            return payload["value"]
                except Exception as e:
                    logger.debug("缓存读取失败: %s", e)
                    try:
                        path.unlink()
                    except OSError:
                        pass
            result = func(*args, **kwargs)
            if _cacheable(result):
                _MEMO[key] = (time.time(), result)
                tmp = path.with_suffix(f".{os.getpid()}.tmp")
                try:
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump({"version": __version__, "key": key, "value": result},
                                  f, ensure_ascii=False)
                    os.replace(tmp, path)
                except Exception as e:
                    logger.debug("缓存写入失败: %s", e)
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
            return result
        wrapper.__name__ = getattr(func, "__name__", "cached")
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator


def clear_cache(pattern: Optional[str] = None) -> int:
    """清缓存（磁盘 + 进程内记忆）。pattern 匹配缓存内容里的 key。

    返回**成功删除**的文件数。删除失败（例如沙箱/杀软/权限拒绝）不会中断或抛异常，
    只记一条 warning —— 否则在受限环境里调用它会让整个脚本以非零码退出。
    """
    _MEMO.clear()
    cache_dir = Path(get_config().cache_dir)
    if not cache_dir.exists():
        return 0
    count = 0
    failed = 0
    for f in cache_dir.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            key = payload.get("key", "") if isinstance(payload, dict) else ""
        except Exception:
            key = ""
        if pattern is None or pattern in key:
            try:
                f.unlink(missing_ok=True)
                count += 1
            except OSError as e:                       # 权限/沙箱拒绝：跳过，不影响其余文件
                failed += 1
                logger.warning("删除缓存文件失败（已跳过）%s: %s", f.name, e)
    if failed:
        logger.warning("缓存清理完成：成功 %d 个，失败 %d 个", count, failed)
    return count


# ---------------------------------------------------------------------------
# Layer 0：基础工具
# ---------------------------------------------------------------------------

def normalize_fund_code(code: Any) -> str:
    code = str(code).strip()
    if code.upper().startswith(("OF", "SH", "SZ", "BJ")):
        code = code[2:]
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"无效的基金代码: {code!r}（应为 6 位数字）")
    return code


def safe_get(data: Any, *keys, default=None):
    cur = data
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return default
    return default if cur is None else cur


def to_float(value, default: Optional[float] = None) -> Optional[float]:
    """把 '1.23%' / '--' / None / '' 统一转成 float 或 default。"""
    if value is None:
        return default
    s = str(value).strip().replace("%", "").replace(",", "")
    if s in ("", "-", "--", "N/A", "nan", "None"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _js_var(text: str, name: str) -> Optional[str]:
    """从 pingzhongdata 之类的 JS 里取出 var name = ...; 的字面量。"""
    m = re.search(rf"var\s+{re.escape(name)}\s*=\s*(.*?);\s*(?:/\*|var\s|$)", text, re.DOTALL)
    return m.group(1).strip() if m else None


def _ts_to_date(ms: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Layer 1：数据源
# ---------------------------------------------------------------------------

_SEARCH_URL = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
_PZ_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
_TYPETABLE_URL = "https://fund.eastmoney.com/js/fundcode_search.js"
_RANK_URL = "https://fund.eastmoney.com/data/rankhandler.aspx"
_COMPANY_URL = "https://fundmobapi.eastmoney.com/FundMApi/FundCompanyBaseList.ashx"
_BIGDATA_URL = "https://appconfig2.1234567.com.cn/config/BigDataList"
_HOLDINGS_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# fundmobapi 这组接口要求带 deviceid/MobileKey（任意 UUID 即可，不需要任何第三方 token）
_DEVICE_ID = str(uuid.uuid4()).upper()


def _mobile_params(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = {"plat": "Android", "appType": "ttjj", "product": "EFund", "Version": "1",
            "deviceid": _DEVICE_ID, "MobileKey": _DEVICE_ID}
    if extra:
        base.update(extra)
    return base


def _search_raw(keyword: str, timeout: Optional[int] = None) -> List[Dict[str, Any]]:
    resp = _http(_SEARCH_URL, params={"m": "1", "key": keyword},
                 headers={"Referer": "https://fund.eastmoney.com/"}, timeout=timeout, source="search")
    resp.encoding = "utf-8"
    text = resp.text.strip()
    if not text:
        raise FundDataError("搜索接口返回空响应")
    if text.endswith(")") and "(" in text:                    # 去掉 JSONP 包裹
        text = text[text.find("(") + 1:-1].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise FundDataError(f"搜索接口 JSON 解析失败: {e}") from e
    return data.get("Datas") or []


def search_fund(keyword: str) -> List[Dict[str, Any]]:
    """搜索基金（按代码或名称）。返回上游原始条目列表。"""
    keyword = str(keyword).strip()
    if not keyword:
        return []
    return _search_raw(keyword)


@_cached(ttl_hours=24)
def _pingzhongdata(code: str) -> str:
    resp = _http(_PZ_URL.format(code=code),
                 headers={"Referer": f"https://fund.eastmoney.com/{code}.html"}, source="pingzhong")
    resp.encoding = "utf-8"
    if len(resp.text) < 1000:
        raise FundDataError(f"{code} 的净值数据异常（长度 {len(resp.text)}）")
    return resp.text


@_cached(ttl_hours=24)
def get_fund_type_table() -> Dict[str, Dict[str, str]]:
    """全部基金（约 2.8 万只）的 代码 -> {name, type, pinyin}，用于类型识别与名称查询。"""
    resp = _http(_TYPETABLE_URL, headers={"Referer": "https://fund.eastmoney.com/"}, source="typetable")
    resp.encoding = "utf-8"
    m = re.search(r"=\s*(\[.*\])\s*;?\s*$", resp.text.strip(), re.DOTALL)
    if not m:
        raise FundDataError("基金类型表格式变化，无法解析")
    rows = json.loads(m.group(1))
    table: Dict[str, Dict[str, str]] = {}
    for row in rows:
        if len(row) >= 4:
            table[row[0]] = {"pinyin_abbr": row[1], "name": row[2], "type": row[3]}
    if not table:
        raise FundDataError("基金类型表为空")
    return table


@_cached(ttl_hours=6)
def get_fund_rank(sort_column: str = "1nzf", top: int = 0) -> List[Dict[str, Any]]:
    """全量基金排行（约 2 万只），含区间收益。用于筛选器与排行榜。

    sort_column: 1nzf=近1年, rzdf=日增长率, zzf=近1周, 1yzf=近1月, 3yzf=近3月, 6yzf=近6月,
                 2nzf=近2年, 3nzf=近3年, jnzf=今年来, lnzf=成立来
    """
    today = date.today().isoformat()
    last_year = (date.today() - timedelta(days=365)).isoformat()
    params = {
        "op": "ph", "dt": "kf", "ft": "all", "rs": "", "gs": "0",
        "sc": sort_column, "st": "desc", "sd": last_year, "ed": today,
        "qdii": "", "tabSubtype": ",,,,,", "pi": "1",
        "pn": str(top if top > 0 else 30000), "dx": "1", "v": "0.1591891419018292",
    }
    resp = _http(_RANK_URL, params=params,
                 headers={"Referer": "https://fund.eastmoney.com/data/fundranking.html"},
                 timeout=60, source="rank")
    resp.encoding = "utf-8"
    m = re.search(r"datas:\s*(\[.*?\])\s*,\s*allRecords", resp.text, re.DOTALL)
    if not m:
        raise FundDataError("排行接口格式变化，无法解析")
    fields = ["code", "name", "pinyin", "date", "nav", "acc_nav", "daily",
              "w1", "m1", "m3", "m6", "y1", "y2", "y3", "ytd", "since", "custom", "fee"]
    out = []
    for item in json.loads(m.group(1)):
        parts = item.split(",")
        rec = {}
        for i, key in enumerate(fields):
            rec[key] = parts[i] if i < len(parts) else ""
        out.append(rec)
    return out


@_cached(ttl_hours=24)
def get_company_list() -> List[Dict[str, Any]]:
    """基金公司列表（215 家，含旗下基金数量、经理数、成立日）。

    该接口必须带 deviceid/MobileKey，否则返回 ErrCode 63116。
    """
    resp = _http(_COMPANY_URL, params=_mobile_params(),
                 headers={"Referer": "https://fund.eastmoney.com/"}, source="company")
    resp.encoding = "utf-8"
    data = resp.json()
    if data.get("ErrCode") not in (0, None):
        raise FundDataError(f"公司列表接口错误: ErrCode={data.get('ErrCode')} "
                            f"ErrMsg={data.get('ErrMsg')}")
    items = data.get("Datas") or []
    if not items:
        raise FundDataError("公司列表为空")
    return items


@_cached(ttl_hours=12)
def get_bigdata_list() -> List[Dict[str, Any]]:
    """大数据榜单（14 个榜单，替代原 Node.js 的 /bigDataList 与行业主题列表）。"""
    resp = _http(_BIGDATA_URL, headers={"User-Agent": UA_MOBILE}, source="bigdata")
    resp.encoding = "utf-8"
    data = resp.json()
    items = data.get("datas") or []
    if not items:
        raise FundDataError("大数据榜单为空")
    return items


def get_holdings(code: str, include_previous: bool = False):
    """基金持仓。页面含两张表（本季度、上季度），原实现只取了第一张，
    导致“较上季度”永远是同一份数据自己比自己。

    include_previous=False -> 返回 list[dict]（最新一期披露）
    include_previous=True  -> 返回 (latest, previous)

    ⚠️ 披露口径提醒：季报只披露前十大，半年报/年报披露全部持仓。
    因此当最新一期是半年报（常见 70+ 条）而上期是季报（10 条）时，
    两期直接相减会出现大量虚假的“新增”，这不是持仓变动，而是披露范围不同。
    """
    code = normalize_fund_code(code)
    now = datetime.now()
    resp = _http(_HOLDINGS_URL,
                 params={"type": "jjcc", "code": code, "topline": "100",
                         "year": now.strftime("%Y"), "month": now.strftime("%m")},
                 headers={"Referer": f"https://fundf10.eastmoney.com/ccmx_{code}.html"},
                 source="holdings")
    if "暂无数据" in resp.text:
        raise FundDataError(f"{code} 暂无持仓数据")
    resp.encoding = resp.apparent_encoding or "utf-8"

    # 注意：页面用的是单引号 <table class='w782 comm tzxq'>，两种引号都要兼容
    tables = re.findall(r"<table[^>]*class=['\"]w782[^>]*>.*?</table>", resp.text, re.DOTALL)

    def parse(table_html: str) -> List[Dict[str, str]]:
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
            if len(tds) >= 7:
                clean = lambda s: re.sub(r"<[^>]+>", "", s).strip()
                rows.append({"code": clean(tds[1]), "name": clean(tds[2]),
                             "ratio": to_float(clean(tds[6]), 0.0)})
        return rows

    latest = parse(tables[0]) if tables else []
    previous = parse(tables[1]) if len(tables) > 1 else []
    if not latest:
        raise FundDataError(f"{code} 持仓表为空或结构已变化")
    return (latest, previous) if include_previous else latest


_INDEX_MAP = {
    "000300": "1.000300", "000905": "1.000905", "000016": "1.000016",
    "000012": "1.000012", "000688": "1.000688", "399006": "0.399006",
    "399001": "0.399001", "399005": "0.399005",
}
INDEX_NAMES = {
    "000300": "沪深300", "000905": "中证500", "000016": "上证50",
    "000012": "国债指数", "000688": "科创50", "399006": "创业板指",
    "399001": "深证成指", "399005": "中小板指",
}


@_cached(ttl_hours=12)
def get_index_kline(index_code: str, days: int = 365) -> List[Tuple[str, float]]:
    """指数日线（用于报告基准）。按日历天截取，与基金净值同口径。

    数据源顺序：**新浪优先，东财兜底**。
    原因：`push2his.eastmoney.com` 在部分网络/代理环境下会被稳定拦截
    （实测 3/3 失败），把它放主源会导致每次未命中缓存都要白等一轮重试。
    两个源都能给到约 1000 根日线（≈4 年），覆盖报告用到的 3y 窗口。
    """
    try:
        return _index_kline_sina(index_code, days)
    except FundToolkitError as e:
        logger.warning("新浪指数接口不可用（%s），回退东财", e)
    return _index_kline_em(index_code, days)


def _index_kline_em(index_code: str, days: int) -> List[Tuple[str, float]]:
    secid = _INDEX_MAP.get(index_code)
    if not secid:
        secid = index_code if "." in index_code else f"1.{index_code}"
    beg = (date.today() - timedelta(days=days + 30)).strftime("%Y%m%d")
    resp = _http(_KLINE_URL, params={
        "secid": secid, "fields1": "f1,f2,f3,f4,f5", "fields2": "f51,f53",
        "klt": "101", "fqt": "1", "beg": beg, "end": "20500101", "lmt": "1000",
    }, headers={"Referer": "https://quote.eastmoney.com/"}, source="kline_em")
    data = (resp.json().get("data") or {})
    series = []
    for line in data.get("klines") or []:
        p = line.split(",")
        if len(p) >= 2:
            series.append((p[0], float(p[1])))
    if len(series) < 2:
        raise FundDataError(f"指数 {index_code} 无K线数据")
    cutoff = (datetime.strptime(series[-1][0], "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    return [x for x in series if x[0] >= cutoff]


_SINA_INDEX = {"000300": "sh000300", "000905": "sh000905", "000016": "sh000016",
               "000012": "sh000012", "000688": "sh000688", "399006": "sz399006",
               "399001": "sz399001", "399005": "sz399005"}
_SINA_KLINE_URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                   "CN_MarketData.getKLineData")


def _index_kline_sina(index_code: str, days: int) -> List[Tuple[str, float]]:
    sym = _SINA_INDEX.get(index_code) or (
        f"sz{index_code}" if index_code.startswith("39") else f"sh{index_code}")
    resp = _http(_SINA_KLINE_URL,
                 params={"symbol": sym, "scale": "240", "ma": "no", "datalen": "1023"},
                 headers={"Referer": "https://finance.sina.com.cn/"}, source="kline_sina")
    try:
        data = resp.json()
    except ValueError as e:
        raise FundDataError(f"新浪指数接口返回非 JSON: {e}") from e
    series = [(x["day"], float(x["close"])) for x in (data or [])
              if isinstance(x, dict) and x.get("day") and x.get("close")]
    if len(series) < 2:
        raise FundDataError(f"指数 {index_code}({sym}) 无可用K线数据")
    series.sort(key=lambda x: x[0])
    cutoff = (datetime.strptime(series[-1][0], "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    return [x for x in series if x[0] >= cutoff]


# ---------------------------------------------------------------------------
# Layer 2：基金基础信息
# ---------------------------------------------------------------------------

def get_fund_basic_info(code: str, allow_fuzzy: bool = False) -> Dict[str, Any]:
    """搜索接口的原始条目。默认要求精确命中，避免把股票当成基金返回。"""
    code = normalize_fund_code(code)
    results = search_fund(code)
    if not results:
        raise FundNotFoundError(f"未找到基金: {code}")
    for item in results:
        if item.get("CODE") == code:
            return item
    if not allow_fuzzy:
        raise FundNotFoundError(f"未找到基金: {code}（搜索仅返回近似结果 {results[0].get('CODE')}）")
    logger.warning("模糊匹配: %s -> %s %s", code, results[0].get("CODE"), results[0].get("NAME"))
    return results[0]


def get_fund_name(code: str) -> Optional[str]:
    try:
        info = get_fund_basic_info(code)
        return info.get("NAME") or None
    except (FundNotFoundError, FundConnectionError, FundDataError, ValueError):
        pass
    table = _safe_type_table()
    return (table.get(str(code)) or {}).get("name")


def get_fund_type(code: str) -> Optional[str]:
    """基金类型。优先用全量类型表（细粒度，如 '指数型-股票'），其次搜索接口。"""
    table = _safe_type_table()
    t = (table.get(str(code)) or {}).get("type")
    if t:
        return t
    try:
        return get_fund_basic_info(code).get("CATEGORYDESC") or None
    except Exception:
        return None


def _safe_type_table() -> Dict[str, Dict[str, str]]:
    try:
        return get_fund_type_table()
    except Exception as e:
        logger.debug("类型表不可用: %s", e)
        return {}


def get_fund_net_value(code: str) -> Optional[Dict[str, Any]]:
    try:
        nav = safe_get(get_fund_basic_info(code), "FundBaseInfo")
        return nav or None
    except (FundNotFoundError, FundConnectionError, FundDataError, ValueError):
        return None


def get_fund_manager(code: str) -> Optional[str]:
    return safe_get(get_fund_net_value(code), "JJJL")


def get_fund_company(code: str) -> Optional[str]:
    return safe_get(get_fund_net_value(code), "JJGS")


def get_latest_net_value(code: str) -> Optional[Dict[str, Any]]:
    return get_fund_net_value(code)


# ---------------------------------------------------------------------------
# Layer 3：历史净值（单位净值 + 累计净值 + 分红）与复权
# ---------------------------------------------------------------------------

def get_nav_history(code: str, days: int = 365) -> List[Dict[str, Any]]:
    """历史净值序列（升序）。每项: date, nav(单位净值), acc(累计净值), adj(复权净值), dividend。

    复权口径：r_t = (acc_t - acc_{t-1}) / nav_{t-1}，adj = cumprod(1+r)。
    这样分红/拆分不会被当成暴跌（原实现直接用单位净值，分红日产生虚假回撤）。
    货币基金走独立字段（每万份收益 / 7日年化），单位净值恒为 1 无意义。
    """
    code = normalize_fund_code(code)
    text = _pingzhongdata(code)

    net_raw = _js_var(text, "Data_netWorthTrend")
    if net_raw:
        try:
            rows = json.loads(net_raw)
        except json.JSONDecodeError as e:
            raise FundDataError(f"{code} 净值序列解析失败: {e}") from e
    else:
        rows = None

    acc_raw = _js_var(text, "Data_ACWorthTrend")
    acc_map: Dict[str, float] = {}
    if acc_raw:
        try:
            for item in json.loads(acc_raw):
                d = _ts_to_date(item[0])
                if d:
                    acc_map[d] = float(item[1])
        except (json.JSONDecodeError, ValueError, IndexError):
            acc_map = {}

    series: List[Dict[str, Any]] = []
    if rows:
        for r in rows:
            d = _ts_to_date(r.get("x"))
            nav = to_float(r.get("y"))
            if not d or nav is None:
                continue
            # 注意：JS 里的 unitMoney 只写了“分红：每10份派现金元”，金额是空的，
            # 所以分红金额不用它解析，统一在后面用累计净值反推。
            series.append({"date": d, "nav": nav, "acc": acc_map.get(d), "dividend": None})
    else:
        # 货币基金：每万份收益 + 7 日年化
        mi = _js_var(text, "Data_millionCopiesIncome")
        sy = _js_var(text, "Data_sevenDaysYearIncome")
        if not mi:
            raise FundDataError(f"{code} 无可用净值数据（可能是新基金或已清盘）")
        income = json.loads(mi)
        seven = {}
        if sy:
            for item in json.loads(sy):
                d = _ts_to_date(item[0])
                if d:
                    seven[d] = float(item[1])
        for item in income:
            d = _ts_to_date(item[0])
            if not d:
                continue
            series.append({"date": d, "nav": None, "acc": None, "dividend": None,
                           "income_per_10k": float(item[1]), "seven_day": seven.get(d)})

    if not series:
        raise FundDataError(f"{code} 净值序列为空")
    series.sort(key=lambda x: x["date"])

    if series[0].get("nav") is None:                            # 货币基金不计算复权
        for row in series:
            row["adj"] = 1.0
    else:
        adj = 1.0
        prev = None
        for row in series:
            cur_acc = row["acc"]
            if prev is not None and cur_acc is not None and prev["acc"] is not None and prev["nav"]:
                r = (cur_acc - prev["acc"]) / prev["nav"]
                adj = adj * (1.0 + r)
                # 每份分红 = Δ累计净值 - Δ单位净值（累计净值与单位净值为加性关系时成立）
                div = (cur_acc - prev["acc"]) - (row["nav"] - prev["nav"])
                if div > 1e-9:
                    row["dividend"] = round(div, 4)
            row["adj"] = adj
            prev = row

    if days and days > 0:
        cutoff = (datetime.strptime(series[-1]["date"], "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
        series = [r for r in series if r["date"] >= cutoff]
    if len(series) < 2:
        raise FundDataError(f"{code} 在最近 {days} 天内净值数据不足")

    # 复权序列以窗口首日为 1.0，便于比较
    base = series[0]["adj"]
    if base:
        for row in series:
            row["adj"] = row["adj"] / base
    return series


def is_money_fund(code: str) -> bool:
    """货币基金判定：类型表含“货币”，或净值序列走万份收益字段。"""
    t = get_fund_type(code) or ""
    if "货币" in t or "理财" in t:
        return True
    try:
        text = _pingzhongdata(normalize_fund_code(code))
        return _js_var(text, "Data_netWorthTrend") is None and _js_var(text, "Data_millionCopiesIncome") is not None
    except Exception:
        return False


def get_adjusted_series(code: str, days: int = 365) -> List[Dict[str, Any]]:
    """复权净值序列（date/nav/adj）。全部指标都应基于它，而不是单位净值。"""
    return get_nav_history(code, days)


# ---------------------------------------------------------------------------
# Layer 4：基金类型识别（有序优先级，修正 dict 顺序导致指数基金误判）
# ---------------------------------------------------------------------------

# 关键词按“具体优先”排列，必须是有序列表，不能依赖 dict 顺序
_TYPE_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("货币型",     ("货币", "理财", "现金", "每万份")),
    ("可转债型",   ("可转债", "转债")),
    ("纯债型",     ("纯债", "中短债", "长债", "信用债", "利率债", "债券型", "固收")),
    ("指数型",     ("指数", "ETF", "LOF", "联接")),
    ("QDII",       ("QDII", "海外", "全球", "美元")),
    ("商品型",     ("商品", "黄金", "油气", "白银")),
    ("FOF",        ("FOF", "基金中基金")),
    ("偏债混合型", ("偏债", "保守配置", "混合二级", "混合一级")),
    ("偏股混合型", ("偏股", "积极配置")),
    ("灵活配置型", ("灵活配置", "平衡", "混合型-灵活")),
    ("主动股票型", ("股票型", "股票")),
]

# 风险等级映射（投资者 C1-C5 -> 可投资的基金推断风险等级）
FUND_TYPE_RISK: Dict[str, str] = {
    "货币型": "R1", "纯债型": "R2", "偏债混合型": "R2", "可转债型": "R3",
    "灵活配置型": "R3", "偏股混合型": "R3", "FOF": "R3",
    "指数型": "R4", "主动股票型": "R4", "QDII": "R4", "商品型": "R5",
}

RISK_MAPPING: Dict[str, List[str]] = {
    "C1": ["R1"],
    "C2": ["R1", "R2"],
    "C3": ["R1", "R2", "R3"],
    "C4": ["R1", "R2", "R3", "R4"],
    "C5": ["R1", "R2", "R3", "R4", "R5"],
}

ASSET_ALLOCATION: Dict[str, Dict[str, int]] = {
    "C1": {"股票": 0, "债券": 80, "货币": 20},
    "C2": {"股票": 10, "债券": 70, "货币": 20},
    "C3": {"股票": 30, "债券": 55, "货币": 15},
    "C4": {"股票": 50, "债券": 40, "货币": 10},
    "C5": {"股票": 70, "债券": 25, "货币": 5},
}

# 各投资者等级构建候选池时的风险档位优先顺序。
# 说明：RISK_MAPPING 是嵌套集合（C3⊂C4⊂C5），若只按“收益排序取前 N 只”，
# C3/C4/C5 会得到同一批高分基金。这里按档位优先取候选，使各等级真正落在
# 对应风险层：C1 货币、C2 债券、C3 混合、C4/C5 权益。
# C5 把商品型(R5)作为卫星放在权益之后——R5 数量少且波动极大，
# 不宜作为进取型投资者的核心持仓。
_LEVEL_POOL_ORDER: Dict[str, List[str]] = {
    "C1": ["R1"],
    "C2": ["R2", "R1"],
    "C3": ["R3", "R2", "R1"],
    "C4": ["R4", "R3", "R2", "R1"],
    "C5": ["R4", "R5", "R3", "R2", "R1"],
}

INVESTOR_DESC = {
    "C1": "保守型：追求本金安全，可接受极低收益",
    "C2": "稳健型：追求稳定收益，可接受小幅波动",
    "C3": "平衡型：追求资产增值，接受中等波动",
    "C4": "积极型：追求较高收益，接受较大波动",
    "C5": "进取型：追求高收益，接受大幅波动",
}


def _type_from_text(raw: str, name: str = "") -> str:
    """把上游类型字符串归一到内部 11 类型。不发起任何网络请求。"""
    # 债券指数按债券口径评分（原实现会落到股票口径阈值）
    if "债券指数" in raw or "指数型-固收" in raw:
        return "纯债型"
    text = raw or name
    for type_name, keywords in _TYPE_RULES:
        if any(kw in text for kw in keywords):
            return type_name
    if name:
        if "指数" in name or "ETF" in name:
            return "指数型"
        if "债" in name and "可转债" not in name:
            return "纯债型"
        if any(k in name for k in ("QDII", "海外", "全球")):
            return "QDII"
    return "灵活配置型"


def detect_fund_type(code: str) -> str:
    """把上游类型（如 '指数型-股票' / 'QDII-混合偏股'）归一到内部类型。"""
    raw = get_fund_type(code) or ""
    name = "" if raw else (get_fund_name(code) or "")
    return _type_from_text(raw, name)


def detect_fund_risk(code: str) -> str:
    """按类型推断风险等级（注意：这是推断，不是基金合同约定的正式 R 级）。"""
    return FUND_TYPE_RISK.get(detect_fund_type(code), "R3")


# ---------------------------------------------------------------------------
# Layer 5：指标计算（纯 Python，无 numpy/pandas）
# ---------------------------------------------------------------------------

def calc_max_drawdown(rows: Sequence[Dict[str, Any]], use_adj: bool = True) -> Dict[str, Any]:
    """最大回撤（基于复权净值）。返回回撤百分比、峰值日、谷底日、是否已修复。"""
    key = "adj" if use_adj and rows and rows[0].get("adj") is not None else "nav"
    vals = [(r["date"], r[key]) for r in rows if r.get(key)]
    if len(vals) < 2:
        return {"max_drawdown": 0.0, "peak_date": None, "trough_date": None, "recovered": None}
    peak_d, peak_v = vals[0]
    best_dd, best_peak, best_trough = 0.0, peak_d, peak_d
    for d, v in vals:
        if v > peak_v:
            peak_v, peak_d = v, d
        dd = (peak_v - v) / peak_v * 100 if peak_v else 0.0
        if dd > best_dd:
            best_dd, best_peak, best_trough = dd, peak_d, d
    recovered = None
    if best_dd > 0:
        trough_v = next(v for d, v in vals if d == best_trough)
        recovered = any(v >= trough_v / (1 - best_dd / 100) for d, v in vals if d > best_trough)
    return {"max_drawdown": round(best_dd, 2), "peak_date": best_peak,
            "trough_date": best_trough, "recovered": recovered}


def calc_metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """区间指标。年化一律按真实日历跨度，不再用点数或硬编码 1/3。"""
    key = "adj" if rows and rows[0].get("adj") is not None else "nav"
    vals = [r[key] for r in rows if r.get(key)]
    dates = [r["date"] for r in rows if r.get(key)]
    if len(vals) < 2:
        return {"insufficient": True}
    span_days = (datetime.strptime(dates[-1], "%Y-%m-%d") - datetime.strptime(dates[0], "%Y-%m-%d")).days
    years = span_days / 365.25
    total_return = (vals[-1] / vals[0] - 1) * 100
    annual = ((1 + total_return / 100) ** (1 / years) - 1) * 100 if years > 0 else None
    rets = [(vals[i] / vals[i - 1] - 1) for i in range(1, len(vals)) if vals[i - 1]]
    volatility = statistics.stdev(rets) * (252 ** 0.5) * 100 if len(rets) > 1 else None
    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else None
    peak = vals[0]
    highs = 0
    for v in vals:
        if v >= peak:
            peak = v
            highs += 1
    new_high_ratio = highs / len(vals) * 100
    dd = calc_max_drawdown(rows)
    calmar = (annual / dd["max_drawdown"]) if (annual is not None and dd["max_drawdown"] > 0) else None
    return {
        "insufficient": False, "span_days": span_days, "years": round(years, 2),
        "total_return": round(total_return, 2),
        "annual_return": round(annual, 2) if annual is not None else None,
        "max_drawdown": dd["max_drawdown"], "dd_peak": dd["peak_date"],
        "dd_trough": dd["trough_date"], "dd_recovered": dd["recovered"],
        "volatility": round(volatility, 2) if volatility is not None else None,
        "win_rate": round(win_rate, 2) if win_rate is not None else None,
        "new_high_ratio": round(new_high_ratio, 2),
        "calmar": round(calmar, 2) if calmar is not None else None,
    }


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / ((sxx * syy) ** 0.5)


def calculate_correlation(codes: Sequence[str], days: int = 365) -> Dict[str, Any]:
    """相关性矩阵。用**基金代码**做键（原实现用名称，同名基金会互相覆盖）。"""
    codes = list(dict.fromkeys(normalize_fund_code(c) for c in codes))
    if len(codes) < 2:
        raise ValueError("相关性分析至少需要 2 只基金")
    series: Dict[str, Dict[str, float]] = {}
    for code in codes:
        try:
            rows = get_nav_history(code, days)
        except FundToolkitError as e:
            logger.warning("跳过 %s: %s", code, e)
            continue
        rets = {}
        key = "adj" if rows[0].get("adj") is not None else "nav"
        for i in range(1, len(rows)):
            if rows[i - 1][key]:
                rets[rows[i]["date"]] = rows[i][key] / rows[i - 1][key] - 1
        if len(rets) >= 30:
            series[code] = rets
    if len(series) < 2:
        raise FundDataError("可用收益率序列不足 2 只，无法计算相关性")

    common = set.intersection(*[set(v) for v in series.values()])
    common = sorted(common)
    shortest = min(len(v) for v in series.values())
    required = max(30, int(0.5 * shortest))
    if len(common) < required:
        raise FundDataError(f"对齐后共同交易日仅 {len(common)} 天（需 ≥{required}），相关性不可信")

    codes_ok = list(series)
    matrix = {}
    for i, a in enumerate(codes_ok):
        for b in codes_ok[i:]:
            r = _pearson([series[a][d] for d in common], [series[b][d] for d in common])
            matrix[(a, b)] = matrix[(b, a)] = round(r, 3) if r is not None else None
    return {"codes": codes_ok,
            "names": {c: (get_fund_name(c) or c) for c in codes_ok},
            "common_days": len(common), "matrix": matrix}


def find_similar_funds(target: str, candidates: Sequence[str], days: int = 365,
                       threshold: float = 0.7) -> Dict[str, Any]:
    """找出与目标高度正相关的基金；强负相关单独归组（原实现把 -0.85 当“重复配置”）。

    签名提醒：`target` 是**单个**基金代码字符串，候选放在 `candidates` 里。
        ✅ find_similar_funds("110011", ["519069", "000001"])
        ❌ find_similar_funds(["110011", "519069"], ...)   # 会报错
    """
    if not isinstance(target, str):
        raise ValueError(
            "find_similar(target, candidates)：target 必须是单个基金代码字符串，"
            "候选基金请放进 candidates，例如 find_similar('110011', ['519069', '000001'])")
    target = normalize_fund_code(target)
    cands = [c for c in dict.fromkeys(normalize_fund_code(c) for c in candidates) if c != target]
    corr = calculate_correlation([target] + cands, days)
    if target not in corr["codes"]:
        return {"error": f"{target} 历史数据不足，无法计算相关性"}
    similar, hedges, low = [], [], []
    for c in cands:
        if c not in corr["codes"]:
            continue
        v = corr["matrix"][(target, c)]
        if v is None:
            continue
        item = {"code": c, "name": corr["names"][c], "correlation": v}
        if v >= threshold:
            similar.append(item)
        elif v <= -threshold:
            hedges.append(item)
        else:
            low.append(item)
    similar.sort(key=lambda x: x["correlation"], reverse=True)
    hedges.sort(key=lambda x: x["correlation"])
    low.sort(key=lambda x: abs(x["correlation"]))
    return {"target": target, "target_name": corr["names"][target],
            "common_days": corr["common_days"],
            "similar": similar, "hedges": hedges, "uncorrelated": low}


# ---------------------------------------------------------------------------
# Layer 6：评分（阈值方向已修正，配置带自检）
# ---------------------------------------------------------------------------
# 每项: w=权重(收益,风险,性价比,稳定)，r1/r3=区间收益阈值，dd/vol=回撤/波动阈值，
#       wr=日胜率，nh=创新高占比，cal=卡玛。
# 约定：r1/r3/wr/nh/cal 越大越好 -> 阈值降序；dd/vol 越小越好 -> 阈值升序。
_SCORE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "主动股票型": {"w": (0.40, 0.20, 0.20, 0.20),
                "r1": [(40, 5), (25, 4.5), (15, 4), (10, 3.5), (5, 3), (0, 2.5), (-10, 2), (-20, 1.5), (-30, 1)],
                "r3": [(25, 5), (18, 4.5), (12, 4), (8, 3.5), (4, 3), (0, 2.5), (-8, 2), (-15, 1.5), (-25, 1)],
                "dd": [(0, 5), (8, 4.5), (15, 4), (20, 3.5), (25, 3), (30, 2.5), (40, 2), (50, 1.5)],
                "vol": [(0, 5), (8, 4.5), (15, 4), (20, 3.5), (25, 3), (30, 2.5), (35, 2), (45, 1.5)],
                "wr": [(58, 5), (55, 4.5), (52, 4), (50, 3.5), (48, 3), (45, 2.5), (40, 2)],
                "nh": [(25, 5), (20, 4.5), (15, 4), (10, 3.5), (5, 3), (2, 2.5), (0, 2)],
                "cal": [(3, 5), (2, 4.5), (1.5, 4), (1, 3.5), (0.5, 3), (0, 2.5)]},
    "指数型":   {"w": (0.30, 0.25, 0.25, 0.20),
                "r1": [(35, 5), (20, 4.5), (12, 4), (8, 3.5), (4, 3), (0, 2.5), (-10, 2), (-20, 1.5), (-30, 1)],
                "r3": [(20, 5), (14, 4.5), (10, 4), (6, 3.5), (3, 3), (0, 2.5), (-8, 2), (-15, 1.5), (-25, 1)],
                "dd": [(0, 5), (10, 4.5), (18, 4), (25, 3.5), (30, 3), (35, 2.5), (45, 2)],
                "vol": [(0, 5), (10, 4.5), (18, 4), (25, 3.5), (30, 3), (35, 2.5), (45, 2)],
                "wr": [(55, 5), (52, 4.5), (49, 4), (47, 3.5), (45, 3), (42, 2.5), (38, 2)],
                "nh": [(20, 5), (15, 4.5), (10, 4), (7, 3.5), (4, 3), (2, 2.5), (0, 2)],
                "cal": [(2, 5), (1.5, 4.5), (1, 4), (0.6, 3.5), (0.3, 3), (0, 2.5)]},
    "偏股混合型": {"w": (0.35, 0.25, 0.20, 0.20),
                "r1": [(35, 5), (20, 4.5), (12, 4), (8, 3.5), (4, 3), (0, 2.5), (-10, 2), (-20, 1.5), (-30, 1)],
                "r3": [(22, 5), (15, 4.5), (10, 4), (6, 3.5), (3, 3), (0, 2.5), (-8, 2), (-15, 1.5), (-25, 1)],
                "dd": [(0, 5), (8, 4.5), (15, 4), (20, 3.5), (25, 3), (30, 2.5), (40, 2), (50, 1.5)],
                "vol": [(0, 5), (8, 4.5), (15, 4), (20, 3.5), (25, 3), (30, 2.5), (40, 2)],
                "wr": [(56, 5), (53, 4.5), (50, 4), (48, 3.5), (46, 3), (43, 2.5), (40, 2)],
                "nh": [(22, 5), (17, 4.5), (12, 4), (8, 3.5), (4, 3), (2, 2.5), (0, 2)],
                "cal": [(2.5, 5), (1.8, 4.5), (1.2, 4), (0.8, 3.5), (0.5, 3), (0, 2.5)]},
    "偏债混合型": {"w": (0.25, 0.35, 0.20, 0.20),
                "r1": [(15, 5), (10, 4.5), (7, 4), (5, 3.5), (3, 3), (1, 2.5), (0, 2), (-2, 1.5), (-5, 1)],
                "r3": [(12, 5), (8, 4.5), (6, 4), (4, 3.5), (2.5, 3), (1, 2.5), (0, 2), (-2, 1.5), (-5, 1)],
                "dd": [(0, 5), (3, 4.5), (6, 4), (10, 3.5), (12, 3), (15, 2.5), (20, 2)],
                "vol": [(0, 5), (3, 4.5), (6, 4), (10, 3.5), (12, 3), (15, 2.5), (20, 2)],
                "wr": [(60, 5), (57, 4.5), (54, 4), (52, 3.5), (50, 3), (48, 2.5), (45, 2)],
                "nh": [(30, 5), (25, 4.5), (20, 4), (15, 3.5), (10, 3), (5, 2.5), (0, 2)],
                "cal": [(5, 5), (3, 4.5), (2, 4), (1.2, 3.5), (0.8, 3), (0.5, 2.5)]},
    "灵活配置型": {"w": (0.30, 0.30, 0.20, 0.20),
                "r1": [(30, 5), (18, 4.5), (12, 4), (8, 3.5), (4, 3), (0, 2.5), (-8, 2), (-15, 1.5), (-25, 1)],
                "r3": [(20, 5), (14, 4.5), (10, 4), (6, 3.5), (3, 3), (0, 2.5), (-6, 2), (-12, 1.5), (-20, 1)],
                "dd": [(0, 5), (6, 4.5), (12, 4), (18, 3.5), (22, 3), (28, 2.5), (38, 2)],
                "vol": [(0, 5), (6, 4.5), (12, 4), (18, 3.5), (22, 3), (28, 2.5), (38, 2)],
                "wr": [(57, 5), (54, 4.5), (51, 4), (49, 3.5), (47, 3), (44, 2.5), (40, 2)],
                "nh": [(22, 5), (17, 4.5), (12, 4), (8, 3.5), (4, 3), (2, 2.5), (0, 2)],
                "cal": [(2.5, 5), (1.8, 4.5), (1.2, 4), (0.8, 3.5), (0.5, 3), (0, 2.5)]},
    "纯债型":   {"w": (0.25, 0.35, 0.20, 0.20),
                "r1": [(8, 5), (6, 4.5), (4.5, 4), (3.5, 3.5), (2.5, 3), (1.5, 2.5), (0.5, 2), (0, 1.5), (-1, 1)],
                "r3": [(7, 5), (5.5, 4.5), (4, 4), (3, 3.5), (2, 3), (1, 2.5), (0.5, 2), (0, 1.5), (-1, 1)],
                "dd": [(0, 5), (0.5, 4.5), (1, 4), (1.5, 3.5), (2, 3), (3, 2.5), (5, 2)],
                "vol": [(0, 5), (0.5, 4.5), (1, 4), (1.5, 3.5), (2, 3), (3, 2.5), (5, 2)],
                "wr": [(65, 5), (62, 4.5), (59, 4), (57, 3.5), (55, 3), (52, 2.5), (48, 2)],
                "nh": [(40, 5), (35, 4.5), (30, 4), (25, 3.5), (20, 3), (12, 2.5), (5, 2)],
                "cal": [(15, 5), (10, 4.5), (6, 4), (4, 3.5), (2.5, 3), (1.5, 2.5)]},
    "可转债型": {"w": (0.30, 0.30, 0.20, 0.20),
                "r1": [(20, 5), (14, 4.5), (10, 4), (7, 3.5), (4, 3), (1, 2.5), (-3, 2), (-8, 1.5), (-15, 1)],
                "r3": [(15, 5), (10, 4.5), (7, 4), (5, 3.5), (3, 3), (0, 2.5), (-3, 2), (-8, 1.5), (-15, 1)],
                "dd": [(0, 5), (3, 4.5), (6, 4), (10, 3.5), (15, 3), (20, 2.5), (25, 2)],
                "vol": [(0, 5), (3, 4.5), (6, 4), (10, 3.5), (15, 3), (20, 2.5), (25, 2)],
                "wr": [(58, 5), (55, 4.5), (52, 4), (50, 3.5), (48, 3), (45, 2.5), (40, 2)],
                "nh": [(25, 5), (20, 4.5), (15, 4), (10, 3.5), (6, 3), (3, 2.5), (0, 2)],
                "cal": [(3, 5), (2, 4.5), (1.2, 4), (0.8, 3.5), (0.5, 3), (0, 2.5)]},
    "货币型":   {"w": (0.20, 0.40, 0.20, 0.20),
                "r1": [(3.5, 5), (3, 4.5), (2.5, 4), (2, 3.5), (1.5, 3), (1, 2.5), (0.5, 2)],
                "r3": [(3.5, 5), (3, 4.5), (2.5, 4), (2, 3.5), (1.5, 3), (1, 2.5), (0.5, 2)],
                "dd": [(0, 5), (0.05, 4.5), (0.1, 4), (0.2, 3.5), (0.3, 3), (0.5, 2.5)],
                "vol": [(0, 5), (0.05, 4.5), (0.1, 4), (0.2, 3.5), (0.3, 3), (0.5, 2.5)],
                "wr": [(70, 5), (65, 4.5), (60, 4), (55, 3.5), (50, 3)],
                "nh": [(80, 5), (70, 4.5), (60, 4), (50, 3.5), (40, 3)],
                "cal": [(20, 5), (12, 4.5), (8, 4), (5, 3.5), (3, 3)]},
    "FOF":      {"w": (0.30, 0.30, 0.20, 0.20),
                "r1": [(18, 5), (12, 4.5), (8, 4), (5, 3.5), (3, 3), (0, 2.5), (-4, 2), (-8, 1.5), (-12, 1)],
                "r3": [(14, 5), (9, 4.5), (6, 4), (4, 3.5), (2, 3), (0, 2.5), (-3, 2), (-6, 1.5), (-10, 1)],
                "dd": [(0, 5), (5, 4.5), (10, 4), (15, 3.5), (20, 3), (25, 2.5), (30, 2)],
                "vol": [(0, 5), (5, 4.5), (10, 4), (15, 3.5), (20, 3), (25, 2.5), (30, 2)],
                "wr": [(56, 5), (53, 4.5), (50, 4), (48, 3.5), (46, 3), (43, 2.5), (40, 2)],
                "nh": [(20, 5), (15, 4.5), (10, 4), (7, 3.5), (4, 3), (2, 2.5), (0, 2)],
                "cal": [(2, 5), (1.5, 4.5), (1, 4), (0.6, 3.5), (0.3, 3), (0, 2.5)]},
    "QDII":     {"w": (0.35, 0.25, 0.20, 0.20),
                "r1": [(30, 5), (20, 4.5), (12, 4), (8, 3.5), (4, 3), (-2, 2.5), (-10, 2), (-20, 1.5), (-30, 1)],
                "r3": [(20, 5), (14, 4.5), (10, 4), (6, 3.5), (3, 3), (-2, 2.5), (-8, 2), (-15, 1.5), (-25, 1)],
                "dd": [(0, 5), (10, 4.5), (18, 4), (25, 3.5), (30, 3), (38, 2.5), (50, 2)],
                "vol": [(0, 5), (10, 4.5), (18, 4), (25, 3.5), (30, 3), (38, 2.5), (50, 2)],
                "wr": [(55, 5), (52, 4.5), (49, 4), (47, 3.5), (45, 3), (42, 2.5), (38, 2)],
                "nh": [(20, 5), (15, 4.5), (10, 4), (7, 3.5), (4, 3), (2, 2.5), (0, 2)],
                "cal": [(2, 5), (1.5, 4.5), (1, 4), (0.6, 3.5), (0.3, 3), (0, 2.5)]},
    "商品型":   {"w": (0.35, 0.25, 0.20, 0.20),
                "r1": [(35, 5), (20, 4.5), (12, 4), (6, 3.5), (2, 3), (-5, 2.5), (-15, 2), (-25, 1.5), (-35, 1)],
                "r3": [(22, 5), (15, 4.5), (10, 4), (6, 3.5), (2, 3), (-5, 2.5), (-15, 2), (-25, 1.5), (-35, 1)],
                "dd": [(0, 5), (10, 4.5), (20, 4), (28, 3.5), (35, 3), (45, 2.5), (55, 2)],
                "vol": [(0, 5), (10, 4.5), (20, 4), (28, 3.5), (35, 3), (45, 2.5), (55, 2)],
                "wr": [(55, 5), (52, 4.5), (49, 4), (47, 3.5), (45, 3), (42, 2.5), (38, 2)],
                "nh": [(20, 5), (15, 4.5), (10, 4), (7, 3.5), (4, 3), (2, 2.5), (0, 2)],
                "cal": [(2, 5), (1.5, 4.5), (1, 4), (0.6, 3.5), (0.3, 3), (0, 2.5)]},
}


def _validate_score_configs(configs: Dict[str, Dict[str, Any]]) -> None:
    """阈值方向写错会让评分对任何输入返回同一档（历史 bug：风险控制恒为 5.0）。"""
    for name, cfg in configs.items():
        for key in ("dd", "vol"):
            t = [a for a, _ in cfg[key]]
            if t != sorted(t):
                raise ValueError(f"评分配置 {name}.{key} 必须升序（越小越好），实际 {t}")
        for key in ("r1", "r3", "wr", "nh", "cal"):
            t = [a for a, _ in cfg[key]]
            if t != sorted(t, reverse=True):
                raise ValueError(f"评分配置 {name}.{key} 必须降序（越大越好），实际 {t}")
        if abs(sum(cfg["w"]) - 1.0) > 1e-9:
            raise ValueError(f"评分配置 {name}.w 权重之和应为 1，实际 {sum(cfg['w'])}")


_validate_score_configs(_SCORE_CONFIGS)


def calc_score_5f(value: Optional[float], thresholds: Sequence[Tuple[float, float]],
                  higher_is_better: bool = True) -> Optional[float]:
    """5 分制。higher_is_better=False 用于回撤/波动率这类越小越好的指标。"""
    if value is None:
        return None
    for threshold, score in thresholds:
        if (value >= threshold) if higher_is_better else (value <= threshold):
            return score
    return 0.5


def get_score_config(fund_type: str) -> Dict[str, Any]:
    cfg = _SCORE_CONFIGS.get(fund_type)
    if cfg is None:
        logger.warning("未知基金类型 %r，按灵活配置型评分", fund_type)
        cfg = _SCORE_CONFIGS["灵活配置型"]
    return {"weights": {"收益能力": cfg["w"][0], "风险控制": cfg["w"][1],
                        "性价比": cfg["w"][2], "稳定性": cfg["w"][3]},
            "return_1y": cfg["r1"], "return_3y": cfg["r3"], "max_dd": cfg["dd"],
            "volatility": cfg["vol"], "win_rate": cfg["wr"],
            "new_high": cfg["nh"], "calmar": cfg["cal"]}


def get_fund_score(code: str, days: int = 365) -> Dict[str, Any]:
    """5 维度评分。缺失维度不计入加权；数据不足直接返回“数据不足”，不给分。"""
    code = normalize_fund_code(code)
    name = get_fund_name(code) or code
    ftype = detect_fund_type(code)
    config = get_score_config(ftype)
    out: Dict[str, Any] = {"code": code, "name": name, "type": ftype,
                           "scores": {}, "total": None, "grade": "", "details": {},
                           "insufficient": False}

    if ftype == "货币型":
        rows = get_nav_history(code, days)
        seven = [r.get("seven_day") for r in rows if r.get("seven_day") is not None]
        if not seven:
            out.update(insufficient=True, grade="数据不足（无 7 日年化数据）")
            return out
        avg7 = sum(seven) / len(seven)
        ret_score = calc_score_5f(avg7, config["return_1y"])
        income = [r.get("income_per_10k") for r in rows if r.get("income_per_10k") is not None]
        vol = statistics.stdev(income) if len(income) > 1 else None
        risk_score = calc_score_5f(vol, config["volatility"], higher_is_better=False)
        out["details"] = {"区间": f"{rows[0]['date']} ~ {rows[-1]['date']}",
                          "7日年化均值": round(avg7, 3),
                          "万份收益波动": round(vol, 4) if vol else None}
        out["scores"] = {"收益能力": ret_score, "风险控制": risk_score,
                         "性价比": None, "稳定性": None}
        avail = {k: v for k, v in out["scores"].items() if v is not None}
        if avail:
            total = sum(avail.values()) / len(avail)
            out["total"] = round(total, 2)
            out["grade"] = _grade(total)
        out["note"] = "货币基金按 7 日年化与万份收益波动评分，不使用单位净值口径"
        return out

    rows = get_nav_history(code, days)
    metrics = calc_metrics(rows)
    if metrics.get("insufficient"):
        out.update(insufficient=True, grade="数据不足")
        return out
    # 窗口过短不做年化（避免用外推数字误导）
    annual = metrics["annual_return"] if metrics["years"] >= 0.5 else None
    out["details"] = {
        "区间": f"{rows[0]['date']} ~ {rows[-1]['date']}",
        "区间年数": metrics["years"],
        "区间收益": metrics["total_return"],
        "年化收益": annual,
        "最大回撤": metrics["max_drawdown"],
        "回撤区间": f"{metrics['dd_peak']} → {metrics['dd_trough']}",
        "回撤是否修复": metrics["dd_recovered"],
        "年化波动率": metrics["volatility"],
        "日胜率": metrics["win_rate"],
        "创新高占比": metrics["new_high_ratio"],
        "卡玛比率": metrics["calmar"],
    }
    if annual is None:
        out["note"] = "区间不足半年，未计算年化收益"
    scores = {
        "收益能力": calc_score_5f(metrics["total_return"], config["return_1y"]),
        "风险控制": None,
        "性价比": calc_score_5f(metrics["calmar"], config["calmar"]),
        "稳定性": None,
    }
    dd_s = calc_score_5f(metrics["max_drawdown"], config["max_dd"], higher_is_better=False)
    vol_s = calc_score_5f(metrics["volatility"], config["volatility"], higher_is_better=False)
    dds = [s for s in (dd_s, vol_s) if s is not None]
    scores["风险控制"] = round(sum(dds) / len(dds), 1) if dds else None
    st = [s for s in (calc_score_5f(metrics["win_rate"], config["win_rate"]),
                      calc_score_5f(metrics["new_high_ratio"], config["new_high"])) if s is not None]
    scores["稳定性"] = round(sum(st) / len(st), 1) if st else None
    out["scores"] = scores

    w = config["weights"]
    num = den = 0.0
    for dim, weight in w.items():
        s = scores.get(dim)
        if s is not None:
            num += s * weight
            den += weight
    if den == 0:
        out.update(insufficient=True, grade="数据不足")
        return out
    total = num / den
    out["total"] = round(total, 2)
    out["grade"] = _grade(total)
    if den < sum(w.values()) - 1e-9:
        out["note"] = "部分维度数据缺失，总分按可用维度加权"
    return out


def _grade(total: float) -> str:
    if total >= 4.5:
        return "⭐⭐⭐⭐⭐ 优秀"
    if total >= 4.0:
        return "⭐⭐⭐⭐ 良好"
    if total >= 3.0:
        return "⭐⭐⭐ 一般"
    if total >= 2.0:
        return "⭐⭐ 较差"
    return "⭐ 不推荐"


# ---------------------------------------------------------------------------
# Layer 7：筛选器（改用全量排行表；收益字段是真实区间收益，不再是“日增长率”）
# ---------------------------------------------------------------------------

def filter_funds(keyword: Optional[str] = None, fund_type: Optional[str] = None,
                 min_return: Optional[float] = None, max_return: Optional[float] = None,
                 period: str = "y1", min_nav: Optional[float] = None,
                 max_nav: Optional[float] = None, top_n: int = 20,
                 sort_desc: bool = True) -> List[Dict[str, Any]]:
    """基金筛选（本地计算，只有 2 次网络请求：排行表 + 类型表，均已缓存）。

    period: w1/m1/m3/m6/y1/y2/y3/ytd/since/daily —— 收益字段为对应区间的真实收益（%），
            原实现的 min_return 实际比的是“日增长率”，语义与命名不符。
    fund_type: 支持上游类型片段（如 "债券型"、"指数型-股票"）或内部类型名（如 "纯债型"、"QDII"）。
    缺失值不参与数值过滤（原实现把缺失当 0.0 参与，会误杀/误选）。

    性能提示：本函数对约 2 万只基金做本地筛选，耗时主要在**首次**拉取排行表与类型表
    （此后走缓存），单次调用通常在 2~5 秒内。若只需要“收益最高的前 N 只”，
    用 `get_rank(top=N)` 更快（只解析一次排行表）。
    """
    table = get_fund_rank(sort_column=_PERIOD_TO_SC.get(period, "1nzf"))
    # 类型表一次性取出后在本地查字典：绝不能放在循环里逐只调用 get_fund_type()，
    # 那会对每只基金都读盘+解析一次 2.4MB 类型表（实测把筛选拖到 480 秒），
    # 且对表里没有的代码还会退化成逐只网络请求。
    type_tbl = _safe_type_table() if fund_type else {}
    out = []
    for rec in table:
        if keyword:
            kw = keyword.lower()
            if kw not in (rec.get("name") or "").lower() and kw not in str(rec.get("code")):
                continue
        if fund_type:
            raw = (type_tbl.get(str(rec.get("code"))) or {}).get("type") or ""
            if not raw:
                continue
            if fund_type not in raw and _type_from_text(raw) != fund_type:
                continue
        ret = to_float(rec.get(period))
        if (min_return is not None or max_return is not None) and ret is None:
            continue
        if min_return is not None and ret is not None and ret < min_return:
            continue
        if max_return is not None and ret is not None and ret > max_return:
            continue
        nav = to_float(rec.get("nav"))
        if min_nav is not None and (nav is None or nav < min_nav):
            continue
        if max_nav is not None and (nav is None or nav > max_nav):
            continue
        item = dict(rec)
        item["period_return"] = ret
        out.append(item)
    key = "period_return"
    out.sort(key=lambda x: (x[key] is None, x[key] if x[key] is not None else 0), reverse=sort_desc)
    return out[:top_n]


_PERIOD_TO_SC = {"w1": "zzf", "m1": "1yzf", "m3": "3yzf", "m6": "6yzf",
                 "y1": "1nzf", "y2": "2nzf", "y3": "3nzf",
                 "ytd": "jnzf", "since": "lnzf", "daily": "rzdf"}


# ---------------------------------------------------------------------------
# Layer 8：定投回测（区间裁剪 + 计划日映射 + XIRR + 分红 + 赎回费）
# ---------------------------------------------------------------------------

def _plan_dates(start: date, end: date, frequency: str,
                day_of_month: int = 1, day_of_week: int = 1) -> List[date]:
    """先生成“计划买入日”，不掺入净值数据。"""
    out: List[date] = []
    if frequency == "monthly":
        y, m = start.year, start.month
        while date(y, m, 1) <= end:
            d = min(day_of_month, calendar.monthrange(y, m)[1])
            cur = date(y, m, d)
            if start <= cur <= end:
                out.append(cur)
            m += 1
            if m > 12:
                y, m = y + 1, 1
    elif frequency == "quarterly":
        y, m = start.year, ((start.month - 1) // 3) * 3 + 1
        while date(y, m, 1) <= end:
            d = min(day_of_month, calendar.monthrange(y, m)[1])
            cur = date(y, m, d)
            if start <= cur <= end:
                out.append(cur)
            m += 3
            if m > 12:
                y, m = y + 1, m - 12
    elif frequency in ("weekly", "biweekly"):
        step = 7 if frequency == "weekly" else 14
        delta = (day_of_week - start.weekday()) % 7
        cur = start + timedelta(days=delta)
        while cur <= end:
            out.append(cur)
            cur += timedelta(days=step)
    else:
        raise ValueError(f"不支持的定投频率: {frequency}（可选 monthly/weekly/biweekly/quarterly）")
    return out


def _map_to_tradable(rows: Sequence[Dict[str, Any]], plan: Sequence[date]) -> Tuple[List[str], int]:
    """把计划日映射到“不早于计划日”的首个有净值日，避免跨月/跨期向前吸附。"""
    dates = [r["date"] for r in rows]
    picked: List[str] = []
    merged = 0
    for d in plan:
        target = d.strftime("%Y-%m-%d")
        idx = None
        for i, ds in enumerate(dates):
            if ds >= target:
                idx = i
                break
        if idx is None:
            continue
        if picked and dates[idx] == picked[-1]:
            merged += 1
            continue
        picked.append(dates[idx])
    return picked, merged


def _xirr(cf_dates: Sequence[date], cf_amounts: Sequence[float]) -> Optional[float]:
    """货币加权收益率（二分法）。定投是分批投入，简单收益率年化会失真。"""
    if len(cf_dates) < 2:
        return None
    t0 = cf_dates[0]
    ts = [(d - t0).days / 365.0 for d in cf_dates]
    if ts[-1] <= 0:
        return None

    def npv(rate: float) -> float:
        return sum(a / (1.0 + rate) ** t for a, t in zip(cf_amounts, ts))

    lo, hi = -0.9999, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _redeem_fee_rate(hold_days: int) -> float:
    if hold_days < 7:
        return 0.015
    if hold_days < 365:
        return 0.005
    if hold_days < 730:
        return 0.0025
    return 0.0


def calculate_drip(code: str, amount: float = 1000.0, start_date: Optional[str] = None,
                   end_date: Optional[str] = None, frequency: str = "monthly",
                   day_of_month: int = 1, day_of_week: int = 1,
                   fee_rate: float = 0.0015, redeem_fee: bool = True) -> Dict[str, Any]:
    """定投回测。

    与旧实现的差别：
      · start/end 真正约束回测区间（旧实现只在买入日生成里过滤局部副本，
        估值与“一次性投入”基准仍用 5 年全量数据）
      · 买入日先按计划生成再映射到可交易日，不跨期向前吸附、不静默丢单
      · 年化用 XIRR
      · 分红通过复权因子计入（旧实现完全忽略现金分红）
      · 赎回费按批次持有期分档扣除
    """
    code = normalize_fund_code(code)
    if amount <= 0:
        raise ValueError(f"定投金额必须大于 0，当前 {amount}")
    if frequency not in ("monthly", "weekly", "biweekly", "quarterly"):
        raise ValueError(f"不支持的定投频率: {frequency}")

    rows = get_nav_history(code, days=365 * 10)
    if rows[0].get("nav") is None:
        raise FundDataError(f"{code} 是货币基金，定投回测请使用净值型基金")

    def _filter(rs):
        s = rs
        if start_date:
            s = [r for r in s if r["date"] >= start_date]
        if end_date:
            s = [r for r in s if r["date"] <= end_date]
        return s

    window = _filter(rows)
    if len(window) < 2:
        raise FundDataError("指定区间内净值数据不足")

    first_day = datetime.strptime(window[0]["date"], "%Y-%m-%d").date()
    last_day = datetime.strptime(window[-1]["date"], "%Y-%m-%d").date()
    plan = _plan_dates(first_day, last_day, frequency, day_of_month, day_of_week)
    buy_dates, merged = _map_to_tradable(window, plan)
    if not buy_dates:
        raise FundDataError("未能生成任何买入日，请检查日期范围与参数")

    by_date = {r["date"]: r for r in window}
    valuation = window[-1]["date"]                      # 估值锚定区间末日
    val_adj = by_date[valuation]["adj"]

    total_cost = 0.0
    total_value = 0.0
    records = []
    for d in buy_dates:
        row = by_date[d]
        net = amount * (1 - fee_rate)
        shares = net / row["nav"]
        total_cost += amount
        # 该批次到估值日的价值 = 投入净额 × 复权增长倍数（分红自动再投资）
        growth = val_adj / row["adj"]
        value = net * growth
        records.append({"date": d, "nav": row["nav"], "amount": amount,
                        "shares": round(shares, 4),
                        "growth_to_valuation": round(growth, 6),
                        "value_at_valuation": round(value, 2)})
        total_value += value

    fee_out = 0.0
    if redeem_fee:
        vd = datetime.strptime(valuation, "%Y-%m-%d").date()
        for rec, d in zip(records, buy_dates):
            hold = (vd - datetime.strptime(d, "%Y-%m-%d").date()).days
            fee_out += rec["value_at_valuation"] * _redeem_fee_rate(hold)
    final_value = total_value - fee_out
    profit = final_value - total_cost
    total_return = profit / total_cost * 100 if total_cost else 0.0

    cf_dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in buy_dates]
    cf_amounts = [-amount] * len(buy_dates)
    cf_dates.append(datetime.strptime(valuation, "%Y-%m-%d").date())
    cf_amounts.append(final_value)
    xirr = _xirr(cf_dates, cf_amounts)

    # 一次性投入基准：与定投同一入场日（旧实现用 5 年窗口首日，比 start_date 早一年多）
    entry = by_date[buy_dates[0]]
    lump_shares = total_cost / entry["nav"]
    lump_value = total_cost * (by_date[valuation]["adj"] / entry["adj"])
    if redeem_fee:
        hold = (datetime.strptime(valuation, "%Y-%m-%d").date()
                - datetime.strptime(buy_dates[0], "%Y-%m-%d").date()).days
        lump_value -= lump_value * _redeem_fee_rate(hold)
    lump_return = (lump_value - total_cost) / total_cost * 100 if total_cost else 0.0

    return {
        "code": code, "name": get_fund_name(code) or code, "frequency": frequency,
        "start_date": buy_dates[0], "end_date": valuation,
        "requested_start": start_date, "requested_end": end_date,
        "num_investments": len(records), "planned_investments": len(plan),
        "merged_investments": merged,
        "total_cost": round(total_cost, 2), "final_value": round(final_value, 2),
        "total_return": round(total_return, 2),
        "annual_return_xirr": round(xirr * 100, 2) if xirr is not None else None,
        "redeem_fee": round(fee_out, 2),
        "lump_sum_cost": round(total_cost, 2), "lump_sum_value": round(lump_value, 2),
        "lump_sum_return": round(lump_return, 2),
        "difference_vs_lump": round(total_return - lump_return, 2),
        "records": records,
        "note": ("区间收益为复权口径（含分红再投资）；年化为 XIRR（货币加权）。"
                 f"计划 {len(plan)} 期，实际执行 {len(records)} 期"
                 + (f"，{merged} 期因无净值顺延合并" if merged else "")),
    }


# ---------------------------------------------------------------------------
# Layer 9：投资建议（C1-C5）
# ---------------------------------------------------------------------------

@dataclass
class FundRecommendation:
    code: str
    name: str
    fund_type: str
    risk_level: str
    score: Optional[float]
    grade: str
    reason: str
    metrics: Dict[str, Any] = field(default_factory=dict)


def recommend_funds(risk_level: str, codes: Optional[Sequence[str]] = None,
                    top_n: int = 10, min_score: float = 0.0,
                    max_drawdown: Optional[float] = None,
                    max_risk: Optional[str] = None,
                    max_candidates: int = 80,
                    max_score: Optional[int] = None) -> List[FundRecommendation]:
    """按投资者风险等级推荐。

    参数
    ----
    max_risk : 可选的风险上限（如 "R2"）。RISK_MAPPING 是嵌套集合
        （C3⊂C4⊂C5），所以 C3/C4/C5 的默认候选池会高度重叠；
        传入 max_risk 可把结果收敛到指定档位以下，例如
        C5 + max_risk="R4" 只看权益类，不掺商品型。

    性能说明
    --------
    `get_fund_score` 每只基金要抓一次净值序列（24h 缓存）。因此这里先用
    **类型表**做零成本的类型/风险筛选，再只对至多 `max_score`
    （默认 max(15, top_n*2)）只基金做完整评分。

    候选池说明
    ----------
    默认从**全量排行**（约 2 万只）里筛，而不是只取收益榜前若干名：
    货币基金年化约 1.5%，永远排不进收益榜前列，只取前列会导致 C1 永远无候选。
    """
    risk_level = str(risk_level).strip().upper()
    if risk_level not in RISK_MAPPING:
        raise ValueError(f"无效的风险等级: {risk_level}（可选 C1-C5）")
    allowed = list(RISK_MAPPING[risk_level])
    if max_risk:
        max_risk = str(max_risk).strip().upper()
        if max_risk not in RISK_MAPPING["C5"]:
            raise ValueError(f"无效的风险上限: {max_risk}（可选 R1-R5）")
        allowed = [r for r in allowed if r <= max_risk]
    max_score = max_score or max(15, top_n * 2)

    if not codes:
        type_tbl = _safe_type_table()
        if not type_tbl:
            raise FundDataError("基金类型表不可用，无法生成候选池")
        # 排行表有真实区间收益，但**不含货币基金**（货币基金是独立榜单），
        # 所以候选池以类型表（覆盖全部 2.8 万只）为准，用排行表的收益做档位内排序。
        rank_return: Dict[str, Optional[float]] = {}
        try:
            for rec in get_fund_rank(top=0):
                c = rec.get("code")
                if c:
                    rank_return[c] = to_float(rec.get("y1"))
        except FundToolkitError as e:
            logger.warning("全量排行不可用，档位内改为按代码排序: %s", e)

        tier_order = [t for t in _LEVEL_POOL_ORDER[risk_level] if not max_risk or t <= max_risk]
        by_tier: Dict[str, List[Tuple[bool, float, str]]] = {t: [] for t in tier_order}
        for c, meta in type_tbl.items():
            tier = FUND_TYPE_RISK.get(_type_from_text(meta.get("type") or ""), "R3")
            if tier not in by_tier:
                continue
            ret = rank_return.get(c)
            by_tier[tier].append((ret is None, -(ret or 0.0), c))

        per_tier = max(1, max_candidates // max(1, len(tier_order)))
        codes = []
        for t in tier_order:                       # 按档位优先级拼接：主档在前
            codes.extend(c for _, _, c in sorted(by_tier[t])[:per_tier])
    codes = list(codes or [])
    if not codes:
        raise FundDataError(f"没有可评估的基金候选（风险档位 {'/'.join(allowed)}）")

    out: List[FundRecommendation] = []
    scored = 0
    for code in codes:
        if scored >= max_score:
            break
        try:
            code = normalize_fund_code(code)
        except ValueError:
            continue
        try:
            ftype = detect_fund_type(code)
            risk = FUND_TYPE_RISK.get(ftype, "R3")
            if risk not in allowed:
                continue
            scored += 1
            score = get_fund_score(code)
            if score.get("total") is None or score["total"] < min_score:
                continue
            dd = (score.get("details") or {}).get("最大回撤")
            if max_drawdown is not None and dd is not None and dd > max_drawdown:
                continue
            reasons = []
            if score["total"] >= 4.5:
                reasons.append("综合评分优秀")
            elif score["total"] >= 4.0:
                reasons.append("综合评分良好")
            sc = score.get("scores") or {}
            if (sc.get("收益能力") or 0) >= 4.0:
                reasons.append("收益能力突出")
            if (sc.get("风险控制") or 0) >= 4.0:
                reasons.append("风险控制优秀")
            out.append(FundRecommendation(
                code=code, name=score["name"], fund_type=ftype, risk_level=risk,
                score=score["total"], grade=score["grade"],
                reason="、".join(reasons) or "符合风险匹配",
                metrics=score.get("details") or {}))
        except (FundToolkitError, ValueError) as e:
            logger.debug("跳过候选 %s: %s", code, e)
            continue
    out.sort(key=lambda x: x.score or 0, reverse=True)
    return out[:top_n]


def _disclaimer() -> List[str]:
    return [
        "",
        "⚠️ 风险提示与免责声明:",
        "  · 本工具输出的 R1-R5 为**按基金类型推断**的风险等级，并非基金合同约定的正式风险等级；",
        "    正式评级请以销售机构的基金风险测评结果为准。",
        "  · 所有收益数据为历史区间数据，不代表未来表现，不构成收益预测或承诺。",
        "  · 数据来自天天基金/东方财富公开接口，可能存在延迟、缺失或错误；",
        "  · 未计入管理费/托管费/销售服务费的持续性影响，费率仅为近似。",
        "  · 本工具不构成针对任何个人的投资建议，不承担投资损失；",
        "    投资前请完成风险承受能力测评，并阅读基金合同与招募说明书。",
    ]


def suggest(risk_level: str, amount: float = 10000, codes: Optional[Sequence[str]] = None,
            top_n: int = 5, max_risk: Optional[str] = None,
            max_score: Optional[int] = None) -> str:
    """生成投资建议文本。

    max_score：最多对多少只基金做完整评分（默认 max(15, top_n*2)）。
    调小可显著缩短耗时——评分需要对每只基金抓一次净值序列。
    """
    risk_level = str(risk_level).strip().upper()
    if risk_level not in RISK_MAPPING:
        return f"❌ 无效的风险等级: {risk_level}，请使用 C1-C5"

    lines = ["📊 投资建议（基于基金类型推断的风险等级，非正式评级）", "",
             f"👤 投资者类型: {risk_level} - {INVESTOR_DESC[risk_level]}",
             f"💰 计划金额: {amount:,.0f} 元", ""]
    alloc = ASSET_ALLOCATION[risk_level]
    lines += ["📈 大类资产配置建议（参考，非强制）:",
              f"  股票 {alloc['股票']}% | 债券 {alloc['债券']}% | 货币 {alloc['货币']}%", ""]

    try:
        recs = recommend_funds(risk_level, codes=codes, top_n=top_n,
                               max_risk=max_risk, max_score=max_score)
    except (FundToolkitError, ValueError) as e:
        lines.append(f"⚠️ 推荐失败: {e}")
        lines += _disclaimer()
        return "\n".join(lines)

    if not recs:
        lines.append(f"⚠️ 未找到匹配 {risk_level} 的基金（可能是候选池数据源不可用或门槛过严）")
        lines += _disclaimer()
        return "\n".join(lines)

    weight = 100.0 / len(recs)
    lines.append("📋 候选基金（等权分配金额；等权 ≠ 资产配置比例）:")
    lines.append("")
    for i, r in enumerate(recs, 1):
        lines.append(f"{i}. {r.name} ({r.code})")
        lines.append(f"   类型: {r.fund_type} | 推断风险: {r.risk_level} | "
                     f"评分: {r.score}/5.0 | 评级: {r.grade}")
        d = r.metrics
        bits = []
        for label, key, unit in (("年化", "年化收益", "%"), ("回撤", "最大回撤", "%"),
                                 ("波动", "年化波动率", "%")):
            v = d.get(key)
            if v is not None:
                bits.append(f"{label}{v}{unit}")
        if bits:
            lines.append(f"   指标: {', '.join(bits)}")
        lines.append(f"   理由: {r.reason}")
        lines.append(f"   建议金额: 约 {amount / len(recs):,.0f} 元（{weight:.0f}%）")
        lines.append("")
    lines += _disclaimer()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Layer 10：HTML 可视化报告（转义 + 基准对齐 + 整图替换）
# ---------------------------------------------------------------------------

def _esc(v: Any) -> str:
    return _html.escape("" if v is None else str(v), quote=True)


def _js(v: Any) -> str:
    """安全 JS 字面量，并阻断 </script> 提前闭合。"""
    return json.dumps(v, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")


def _finite(x: Any) -> Optional[float]:
    """把 NaN/inf/非数值统一成 None，避免写出非法 JSON。"""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _drawdown_series(rows: Sequence[Dict[str, Any]], key: str) -> List[float]:
    """回撤序列（%）。**取回撤深度，为非负数**，0 表示处于新高。"""
    out: List[float] = []
    peak: Optional[float] = None
    for r in rows:
        v = _finite(r.get(key))
        if v is None:
            out.append(0.0)
            continue
        if peak is None or v > peak:
            peak = v
        out.append(round((peak - v) / peak * 100, 2) if peak else 0.0)
    return out


def _drawdown_axis_max(max_dd: float) -> float:
    """回撤图纵轴上限。

    规则（按需求）：1.25 × 最大回撤，向上取整到「好看的整数」——
    目标值 ≥ 5 时以 5 为步长，< 5 时以 0.5 为步长（避免小回撤债基被压成一条直线）。
    这样轴顶永远高于实际最深回撤，波形不会越界。

        max_dd=32.96 -> 41.2 -> 45        max_dd=0.4 -> 0.5 -> 0.5
        max_dd=15.8  -> 19.75 -> 20       max_dd=2.1 -> 2.625 -> 3.0
    """
    target = max(0.0, float(max_dd)) * 1.25
    if target <= 0:
        return 1.0
    step = 5.0 if target >= 5.0 else 0.5
    return math.ceil(target / step) * step


_ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"

_REPORT_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',Roboto,sans-serif;background:#f5f7fa;padding:20px}
.container{max-width:1200px;margin:0 auto}
.header{background:linear-gradient(135deg,#1a3a5c,#2d6a9f);color:#fff;padding:24px 30px;border-radius:12px;margin-bottom:20px}
.header h1{font-size:24px;font-weight:600}.header .sub{font-size:14px;opacity:.85;margin-top:6px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.stat-card{background:#fff;padding:14px 18px;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.stat-card .label{font-size:12px;color:#889}.stat-card .value{font-size:20px;font-weight:600;margin-top:4px}
.value.positive{color:#e74c3c}.value.negative{color:#27ae60}.value.neutral{color:#567}
.tabs{display:flex;gap:4px;background:#fff;padding:6px;border-radius:10px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.tab-btn{padding:8px 20px;border:none;border-radius:8px;background:transparent;cursor:pointer;font-size:14px;font-weight:500;color:#567}
.tab-btn:hover{background:#f0f2f5}.tab-btn.active{background:#1a3a5c;color:#fff}
.tab-btn:disabled{opacity:.35;cursor:not-allowed}
.chart-container{background:#fff;border-radius:12px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,.06);margin-bottom:16px}
.chart-box{width:100%;height:420px}.chart-box-small{height:200px}
.footer{color:#9ab;font-size:12px;margin-top:20px;padding:16px;line-height:1.7}
.footer .warn{color:#c0392b}
"""

_REPORT_JS_COMMON = """
if(!window.echarts){document.body.insertAdjacentHTML('afterbegin',
 '<p style="color:#c00;padding:12px">ECharts CDN 加载失败（离线或网络受限），图表不可用。</p>');
 throw new Error('echarts not loaded');}
var FONT={fontFamily:'"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif'};
function deco(btn,keys){document.querySelectorAll('.tab-btn').forEach(function(t){
 var p=t.dataset.period; if(keys.indexOf(p)<0){t.disabled=true;t.style.opacity=.35;}});}
"""


def generate_fund_html_report(fund_code: str, benchmark_code: Optional[str] = None,
                              output_path: Optional[str] = None,
                              periods: Optional[Dict[str, int]] = None) -> str:
    """生成单基金 HTML 报告。output_path 为空时返回 HTML 字符串（原实现隐式返回 None）。"""
    code = normalize_fund_code(fund_code)
    name = get_fund_name(code) or code
    ftype = get_fund_type(code) or ""
    periods = periods or {"3m": 90, "6m": 180, "1y": 365, "3y": 1095}
    if not benchmark_code:
        benchmark_code = "000012" if ("债" in ftype or "货币" in ftype) else "000300"
    bench_name = INDEX_NAMES.get(benchmark_code, benchmark_code)

    max_days = max(periods.values())
    all_rows = get_nav_history(code, max_days)                  # 只取一次，本地切片
    is_money = all_rows[0].get("nav") is None
    try:
        bench_all = dict(get_index_kline(benchmark_code, max_days))
    except FundToolkitError as e:
        logger.warning("基准指数不可用: %s", e)
        bench_all = {}
    bench_dates = sorted(bench_all)

    chart_data: Dict[str, Any] = {}
    last_date = datetime.strptime(all_rows[-1]["date"], "%Y-%m-%d")
    for pname, days in periods.items():
        cutoff = (last_date - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = [r for r in all_rows if r["date"] >= cutoff]
        if len(rows) < 2:
            continue
        dates = [r["date"] for r in rows]
        key = "nav" if is_money else "adj"
        base = rows[0][key]
        series = [round(r[key] / base, 4) for r in rows]
        ret = round((rows[-1][key] / base - 1) * 100, 2)

        bench = None
        bench_ret = None
        bwin = [d for d in bench_dates if d >= dates[0]]
        if len(bwin) >= 2:
            bmap = {d: bench_all[d] for d in bwin}
            filled = []
            lastv = None
            for d in dates:                                     # 对齐到基金日期轴
                if d in bmap:
                    lastv = bmap[d]
                filled.append(lastv)
            if lastv is not None and filled[0] is not None:
                filled = [v if v is not None else filled[0] for v in filled]
                bench = [round(v / filled[0], 4) for v in filled]
                bench_ret = round((filled[-1] / filled[0] - 1) * 100, 2)

        dd = calc_max_drawdown(rows, use_adj=not is_money)
        chart_data[pname] = {
            "dates": dates, "fund": series, "bench": bench,
            "fund_return": ret, "bench_return": bench_ret,
            "max_drawdown": dd["max_drawdown"], "dd_peak": dd["peak_date"],
            "dd_trough": dd["trough_date"], "dd_recovered": dd["recovered"],
            "dd_series": [] if is_money else _drawdown_series(rows, key),
            # 纵轴上限按最大回撤的 1.25 倍取整，保证波形不越界
            "dd_axis": _drawdown_axis_max(dd["max_drawdown"]),
        }

    if not chart_data:
        raise FundDataError(f"{code} 在所选周期内没有可用净值数据，未生成报告")

    tabs = "".join(
        f'<button class="tab-btn" data-period="{k}">{label}</button>'
        for k, label in [("3m", "近3月"), ("6m", "近6月"), ("1y", "近1年"), ("3y", "近3年")])

    footer_bits = [f"数据来源: 天天基金/东方财富公开接口 · 生成时间 {datetime.now():%Y-%m-%d %H:%M}"]
    if is_money:
        footer_bits.append("货币基金按单位净值(恒为1)展示，收益请参考 7 日年化")
    else:
        footer_bits.append("收益与回撤基于<b>复权净值</b>（累计净值差分法，含分红再投资）")
        footer_bits.append("回撤图纵轴为<b>回撤深度</b>（0 = 处于净值新高），轴顶按最大回撤的 1.25 倍取整")
    footer_bits.append('<span class="warn">R 级为按基金类型推断，非基金合同约定的正式风险等级；'
                       '历史业绩不代表未来表现，不构成投资建议。</span>')

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(name)} - 基金分析报告</title>
<script src="{_ECHARTS_CDN}"></script>
<style>{_REPORT_CSS}</style>
</head>
<body>
<div class="container">
<div class="header"><h1>📊 {_esc(name)}</h1>
<div class="sub">{_esc(code)} · {_esc(ftype)} · 基准: {_esc(bench_name)}</div></div>
<div class="stats" id="stats"></div>
<div class="tabs" id="tabs">{tabs}</div>
<div class="chart-container"><div id="chart-main" class="chart-box"></div></div>
<div class="chart-container"><div id="chart-dd" class="chart-box chart-box-small"></div></div>
<div class="footer">{'<br>'.join(footer_bits)}</div>
</div>
<script>
var DATA={_js(chart_data)};
var FUND={_js(name)},BENCH={_js(bench_name)},IS_MONEY={_js(is_money)};
{_REPORT_JS_COMMON}
var mainChart=echarts.init(document.getElementById('chart-main'));
var ddChart=echarts.init(document.getElementById('chart-dd'));
function pct(v){{return v===null||v===undefined?'数据缺失':v+'%';}}
function cls(v){{return v>=0?'positive':'negative';}}
function render(p){{
  var d=DATA[p]; if(!d) return;
  var hasB=d.bench&&d.bench.length>0;
  var s='';
  s+='<div class="stat-card"><div class="label">基金收益</div><div class="value '+cls(d.fund_return)+'">'+d.fund_return+'%</div></div>';
  s+='<div class="stat-card"><div class="label">'+BENCH+'收益</div><div class="value '+(hasB?cls(d.bench_return):'neutral')+'">'+(hasB?d.bench_return+'%':'数据缺失')+'</div></div>';
  s+='<div class="stat-card"><div class="label">超额收益</div><div class="value '+(hasB?cls(d.fund_return-d.bench_return):'neutral')+'">'+(hasB?(d.fund_return-d.bench_return).toFixed(2)+'%':'—')+'</div></div>';
  s+='<div class="stat-card"><div class="label">最大回撤</div><div class="value negative">'+d.max_drawdown+'%</div></div>';
  s+='<div class="stat-card"><div class="label">回撤修复</div><div class="value neutral">'+(d.dd_recovered===true?'已修复':(d.dd_recovered===false?'尚未修复':'无显著回撤'))+'</div></div>';
  document.getElementById('stats').innerHTML=s;

  var series=[{{name:FUND,type:'line',data:d.fund,smooth:true,connectNulls:true,
    lineStyle:{{width:2.5,color:'#e74c3c'}},itemStyle:{{color:'#e74c3c'}},
    areaStyle:{{color:new echarts.graphic.LinearGradient(0,0,0,1,[{{offset:0,color:'rgba(231,76,60,0.25)'}},{{offset:1,color:'rgba(231,76,60,0.02)'}}])}}}}];
  if(hasB){{series.push({{name:BENCH,type:'line',data:d.bench,smooth:true,connectNulls:true,
    lineStyle:{{width:2,color:'#3498db',type:'dashed'}},itemStyle:{{color:'#3498db'}}}});}}
  mainChart.setOption({{
    textStyle:FONT,
    tooltip:{{trigger:'axis',formatter:function(ps){{var h=ps[0].axisValue+'<br/>';
      ps.forEach(function(p){{if(p.value==null)return;
        h+=p.marker+' '+p.seriesName+': '+Number(p.value).toFixed(4)+'<br/>';}});return h;}}}},
    legend:{{top:0,left:'center'}},
    grid:{{top:50,bottom:55,left:55,right:20}},
    xAxis:{{type:'category',data:d.dates,axisLabel:{{fontSize:11,rotate:d.dates.length>60?30:0}},splitLine:{{show:false}}}},
    yAxis:{{type:'value',scale:true,axisLabel:{{fontSize:11}},splitLine:{{lineStyle:{{color:'#eee',type:'dashed'}}}}}},
    series:series,
    dataZoom:[{{type:'slider',start:0,end:100,height:30,bottom:5}},{{type:'inside',start:0,end:100}}]
  }},true);
  if(IS_MONEY){{ddChart.clear();}}
  else{{
    ddChart.setOption({{
      textStyle:FONT,
      tooltip:{{trigger:'axis',formatter:function(ps){{return ps[0].axisValue+'<br/>回撤深度: '+ps[0].value+'%';}}}},
      grid:{{top:15,bottom:25,left:55,right:20}},
      xAxis:{{type:'category',data:d.dates,axisLabel:{{show:false}},splitLine:{{show:false}}}},
      yAxis:{{type:'value',min:0,max:d.dd_axis,axisLabel:{{fontSize:10,formatter:function(v){{return v+'%';}}}},splitLine:{{lineStyle:{{color:'#eee',type:'dashed'}}}}}},
      series:[{{name:'回撤',type:'line',data:d.dd_series,smooth:true,
        lineStyle:{{width:1.5,color:'#27ae60'}},itemStyle:{{color:'#27ae60'}},
        areaStyle:{{color:new echarts.graphic.LinearGradient(0,0,0,1,[{{offset:0,color:'rgba(39,174,96,0.25)'}},{{offset:1,color:'rgba(39,174,96,0.02)'}}])}},
        markPoint:{{data:[{{type:'max',name:'最大回撤'}}],label:{{fontSize:10,fontWeight:'bold',formatter:function(p){{return Number(p.value).toFixed(2)+'%';}}}}}}}}]
    }},true);
  }}
}}
var keys=Object.keys(DATA);
deco(document.getElementById('tabs'),keys);
document.querySelectorAll('.tab-btn').forEach(function(t){{t.addEventListener('click',function(){{
  document.querySelectorAll('.tab-btn').forEach(function(x){{x.classList.remove('active');}});
  this.classList.add('active');render(this.dataset.period);}});}});
if(keys.length){{document.querySelector('.tab-btn[data-period="'+keys[0]+'"]').classList.add('active');render(keys[0]);}}
var rt;window.addEventListener('resize',function(){{clearTimeout(rt);
  rt=setTimeout(function(){{mainChart.resize();ddChart.resize();}},150);}});
</script>
</body></html>"""

    if not output_path:
        return html_doc
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_doc, encoding="utf-8")
    logger.info("HTML 报告已生成: %s", out)
    return str(out)


def generate_compare_report(fund_codes: Sequence[str], benchmark_code: str = "000300",
                            output_path: Optional[str] = None,
                            days: int = 365) -> str:
    """多基金对比报告。收益按统一日期窗口、复权口径计算。"""
    codes = list(dict.fromkeys(normalize_fund_code(c) for c in fund_codes))
    if len(codes) < 2:
        raise ValueError("至少需要 2 只基金才能对比")

    series: Dict[str, Dict[str, float]] = {}
    names: Dict[str, str] = {}
    for code in codes:
        rows = get_nav_history(code, days)
        key = "nav" if rows[0].get("nav") is None else "adj"
        series[code] = {r["date"]: r[key] for r in rows}
        names[code] = get_fund_name(code) or code

    common = sorted(set.intersection(*[set(v) for v in series.values()]))
    if len(common) < 5:
        raise FundDataError(f"各基金共同交易日仅 {len(common)} 天，无法对比")
    try:
        bench_all = dict(get_index_kline(benchmark_code, days))
    except FundToolkitError:
        bench_all = {}
    bwin = [d for d in sorted(bench_all) if d >= common[0]]
    if len(bwin) >= 2:
        bmap = {d: bench_all[d] for d in bwin}
        lastv, filled = None, []
        for d in common:
            if d in bmap:
                lastv = bmap[d]
            filled.append(lastv)
        if filled[0] is None:
            first = next((v for v in filled if v is not None), None)
            filled = [v if v is not None else first for v in filled]
        bench = {d: v for d, v in zip(common, filled)} if filled[0] is not None else {}
    else:
        bench = {}

    colors = ["#e74c3c", "#3498db", "#f39c12", "#2ecc71", "#9b59b6", "#1abc9c", "#e67e22", "#e84393"]
    funds_payload = []
    for i, code in enumerate(codes):
        vals = [series[code][d] for d in common]
        base = vals[0]
        funds_payload.append({
            "code": code, "name": names[code], "color": colors[i % len(colors)],
            "data": [round(v / base, 4) for v in vals],
            "return": round((vals[-1] / base - 1) * 100, 2),
        })
    bench_payload = None
    if bench:
        bvals = [bench[d] for d in common]
        bench_payload = {"name": INDEX_NAMES.get(benchmark_code, benchmark_code),
                         "data": [round(v / bvals[0], 4) for v in bvals],
                         "return": round((bvals[-1] / bvals[0] - 1) * 100, 2)}
    data = {"dates": common, "funds": funds_payload, "benchmark": bench_payload}

    tabs = "".join(f'<button class="tab-btn" data-period="{k}">{v}</button>'
                   for k, v in [("1y", f"近{max(1, round(days / 365))}年")])
    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>基金对比分析</title><script src="{_ECHARTS_CDN}"></script>
<style>{_REPORT_CSS}</style></head><body><div class="container">
<div class="header"><h1>📊 基金对比</h1>
<div class="sub">{_esc(' / '.join(names.values()))} · 基准: {_esc(INDEX_NAMES.get(benchmark_code, benchmark_code))} · 共同交易日 {len(common)} 天</div></div>
<div class="stats" id="stats"></div>
<div class="tabs" id="tabs">{tabs}</div>
<div class="chart-container"><div id="chart-main" class="chart-box" style="height:500px"></div></div>
<div class="footer">数据来源: 天天基金/东方财富公开接口 · 收益为复权口径、统一日期窗口 ·
<span class="warn">历史业绩不代表未来表现，不构成投资建议。</span></div>
</div><script>
var DATA={_js({"1y": data})};
var COLORS={_js(colors)};
{_REPORT_JS_COMMON}
var mainChart=echarts.init(document.getElementById('chart-main'));
function render(p){{
  var d=DATA[p]; if(!d) return;
  var s='';
  d.funds.forEach(function(f,i){{
    s+='<div class="stat-card" style="border-left:4px solid '+f.color+'"><div class="label">'+f.name+'</div>'
      +'<div class="value '+(f.return>=0?'positive':'negative')+'">'+f.return+'%</div></div>';}});
  if(d.benchmark){{s+='<div class="stat-card" style="border-left:4px solid #95a5a6"><div class="label">'+d.benchmark.name+'</div>'
      +'<div class="value '+(d.benchmark.return>=0?'positive':'negative')+'">'+d.benchmark.return+'%</div></div>';}}
  document.getElementById('stats').innerHTML=s;
  var series=d.funds.map(function(f){{
    return {{name:f.name,type:'line',data:f.data,smooth:true,connectNulls:true,
      lineStyle:{{width:2.5,color:f.color}},itemStyle:{{color:f.color}},
      areaStyle:{{color:new echarts.graphic.LinearGradient(0,0,0,1,[{{offset:0,color:f.color+'22'}},{{offset:1,color:f.color+'03'}}])}}}};}});
  if(d.benchmark){{series.push({{name:d.benchmark.name,type:'line',data:d.benchmark.data,
    smooth:true,connectNulls:true,lineStyle:{{width:2,color:'#95a5a6',type:'dashed'}},itemStyle:{{color:'#95a5a6'}}}});}}
  mainChart.setOption({{
    textStyle:FONT,
    tooltip:{{trigger:'axis',formatter:function(ps){{var h=ps[0].axisValue+'<br/>';
      ps.forEach(function(p){{if(p.value==null)return;
        h+=p.marker+' '+p.seriesName+': '+Number(p.value).toFixed(4)+'<br/>';}});return h;}}}},
    legend:{{top:0,left:'center',type:'scroll'}},
    grid:{{top:60,bottom:55,left:55,right:20}},
    xAxis:{{type:'category',data:d.dates,axisLabel:{{fontSize:11,rotate:d.dates.length>60?30:0}},splitLine:{{show:false}}}},
    yAxis:{{type:'value',scale:true,axisLabel:{{fontSize:11}},splitLine:{{lineStyle:{{color:'#eee',type:'dashed'}}}}}},
    series:series,
    dataZoom:[{{type:'slider',start:0,end:100,height:30,bottom:5}},{{type:'inside',start:0,end:100}}]
  }},true);
}}
var keys=Object.keys(DATA);
deco(document.getElementById('tabs'),keys);
document.querySelectorAll('.tab-btn').forEach(function(t){{t.addEventListener('click',function(){{
  document.querySelectorAll('.tab-btn').forEach(function(x){{x.classList.remove('active');}});
  this.classList.add('active');render(this.dataset.period);}});}});
if(keys.length){{document.querySelector('.tab-btn[data-period="'+keys[0]+'"]').classList.add('active');render(keys[0]);}}
var rt;window.addEventListener('resize',function(){{clearTimeout(rt);rt=setTimeout(function(){{mainChart.resize();}},150);}});
</script></body></html>"""

    if not output_path:
        return html_doc
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_doc, encoding="utf-8")
    logger.info("HTML 对比报告已生成: %s", out)
    return str(out)


# ---------------------------------------------------------------------------
# 统一门面
# ---------------------------------------------------------------------------

class FundToolkit:
    """基金工具包统一入口（自包含版：无本地服务、无 akshare）。"""

    def __init__(self, config: Optional[FundToolkitConfig] = None):
        if config:
            set_config(config)
        self._config = get_config()

    @property
    def config(self) -> FundToolkitConfig:
        return self._config

    # 数据
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

    def get_nav_history(self, code: str, days: int = 365) -> List[Dict[str, Any]]:
        return get_nav_history(code, days)

    def get_holdings(self, code: str, include_previous: bool = False):
        return get_holdings(code, include_previous)

    def get_companies(self) -> List[Dict[str, Any]]:
        return get_company_list()

    def get_top_companies(self, top_n: int = 10) -> List[Dict[str, Any]]:
        rows = list(get_company_list())
        rows.sort(key=lambda x: to_float(x.get("FUNDCOUNT"), 0) or 0, reverse=True)
        return rows[:top_n]

    def get_bigdata(self) -> List[Dict[str, Any]]:
        return get_bigdata_list()

    def get_rank(self, sort_column: str = "1nzf", top: int = 50) -> List[Dict[str, Any]]:
        return get_fund_rank(sort_column, top)

    def get_index(self, index_code: str, days: int = 365):
        return get_index_kline(index_code, days)

    # 分析
    def get_score(self, code: str, days: int = 365) -> Dict[str, Any]:
        return get_fund_score(code, days)

    def get_metrics(self, code: str, days: int = 365) -> Dict[str, Any]:
        return calc_metrics(get_nav_history(code, days))

    def filter_funds(self, **kwargs) -> List[Dict[str, Any]]:
        return filter_funds(**kwargs)

    def get_correlation(self, codes: Sequence[str], days: int = 365) -> Dict[str, Any]:
        return calculate_correlation(codes, days)

    def find_similar(self, target: str, candidates: Sequence[str], **kwargs) -> Dict[str, Any]:
        return find_similar_funds(target, candidates, **kwargs)

    def drip(self, code: str, **kwargs) -> Dict[str, Any]:
        return calculate_drip(code, **kwargs)

    def suggest(self, risk_level: str, amount: float = 10000, **kwargs) -> str:
        return suggest(risk_level, amount, **kwargs)

    def recommend(self, risk_level: str, **kwargs) -> List[FundRecommendation]:
        return recommend_funds(risk_level, **kwargs)

    # 可视化
    def generate_report(self, code: str, output_path: Optional[str] = None, **kwargs) -> str:
        return generate_fund_html_report(code, output_path=output_path, **kwargs)

    def generate_compare_report(self, codes: Sequence[str], output_path: Optional[str] = None,
                                **kwargs) -> str:
        return generate_compare_report(codes, output_path=output_path, **kwargs)

    # 工具
    def clear_cache(self, pattern: Optional[str] = None) -> int:
        return clear_cache(pattern)

    def test_connection(self, verbose: bool = False) -> bool:
        return test_connection(verbose)

    def set_log_level(self, level) -> None:
        set_log_level(level)


__all__ = [
    "FundToolkit", "FundToolkitConfig",
    "FundToolkitError", "FundConnectionError", "FundNotFoundError", "FundDataError",
    "search_fund", "get_fund_basic_info", "get_fund_name", "get_fund_type",
    "get_fund_net_value", "get_fund_manager", "get_fund_company",
    "get_nav_history", "get_index_kline", "get_holdings", "get_company_list",
    "get_bigdata_list", "get_fund_rank", "get_fund_type_table",
    "detect_fund_type", "detect_fund_risk", "is_money_fund",
    "calc_metrics", "calc_max_drawdown", "calc_score_5f", "get_score_config",
    "get_fund_score", "filter_funds", "calculate_correlation", "find_similar_funds",
    "calculate_drip", "recommend_funds", "suggest",
    "generate_fund_html_report", "generate_compare_report",
    "clear_cache", "test_connection", "set_log_level", "reset_source_status",
    "get_config", "set_config",
    "RISK_MAPPING", "FUND_TYPE_RISK", "ASSET_ALLOCATION", "INDEX_NAMES",
    "__version__",
]
