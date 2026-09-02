"""
vis.py - 基金可视化扩展包
依赖: pandas, numpy, akshare (echarts 通过 CDN 加载)
"""

import pandas as pd
import numpy as np
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    from fund_toolkit.core import (
        get_fund_name, get_fund_type, get_fund_full_info,
        get_fund_history_by_days, normalize_fund_code, test_connection
    )
except ImportError:
    raise ImportError("请确保 SKILL_FUNDCOUNT.py 在 Python 路径中")


def get_index_data(index_code: str, days: int = 365) -> pd.Series:
    """获取指数历史数据"""
    try:
        import akshare as ak
        symbol_map = {
            "000300": "sh000300", "000012": "sh000012", "000905": "sh000905",
            "000016": "sh000016", "000688": "sh000688", "399006": "sz399006",
            "399001": "sz399001"
        }
        symbol = symbol_map.get(index_code, index_code)
        df = ak.stock_zh_index_daily(symbol=symbol)
        if df is not None and not df.empty:
            df = df.tail(days)
            df['date'] = pd.to_datetime(df['date'])
            return df.set_index('date')['close']
        return pd.Series()
    except Exception as e:
        print(f"[WARN] 获取指数数据失败: {e}")
        return pd.Series()

def normalize_series(series: pd.Series) -> pd.Series:
    """标准化序列到起点为 1.0"""
    if series.empty or series.iloc[0] == 0:
        return series
    return series / series.iloc[0]

def calculate_drawdown_series(nav: pd.Series) -> tuple:
    """计算回撤序列和区间"""
    if nav.empty or len(nav) < 2:
        return pd.DataFrame({"drawdown": []}), []

    cum = nav / nav.iloc[0]
    running_max = cum.expanding().max()
    drawdown = (cum / running_max - 1) * 100
    drawdown_df = pd.DataFrame({"drawdown": drawdown})

    periods = []
    in_drawdown = False
    start_idx = 0
    for i, val in enumerate(drawdown.values):
        if val < -0.01 and not in_drawdown:
            in_drawdown = True
            start_idx = i
        elif val >= -0.01 and in_drawdown:
            in_drawdown = False
            periods.append({
                "start": nav.index[start_idx],
                "end": nav.index[i],
                "max_drawdown": drawdown.iloc[start_idx:i+1].min(),
                "is_active": False
            })
    if in_drawdown:
        periods.append({
            "start": nav.index[start_idx],
            "end": nav.index[-1],
            "max_drawdown": drawdown.iloc[start_idx:].min(),
            "is_active": True
        })
    return drawdown_df, periods

def get_fund_nav_series_vis(code: str, days: int = 365) -> pd.Series:
    """获取基金净值序列"""
    try:
        df = get_fund_history_by_days(code, days)
        if not df.empty:
            return df.set_index('净值日期')['单位净值']
        return pd.Series()
    except Exception as e:
        print(f"[WARN] 获取基金净值失败 {code}: {e}")
        return pd.Series()

def generate_fund_html_report(
    fund_code: str,
    benchmark_code: str = None,
    output_path: str = None
) -> str:
    """生成单基金交互式 HTML 报告"""
    fund_name = get_fund_name(fund_code) or fund_code
    full_info = get_fund_full_info(fund_code)
    fund_type = full_info.get("type", "") or get_fund_type(fund_code) or ""

    BENCHMARKS = {
        "000300": "沪深300", "000012": "国债指数", "000905": "中证500",
        "000016": "上证50", "399006": "创业板指"
    }
    if not benchmark_code:
        benchmark_code = "000012" if ("债券" in fund_type or "债" in fund_type) else "000300"
    benchmark_name = BENCHMARKS.get(benchmark_code, benchmark_code)

    periods = {"3m": 90, "6m": 180, "1y": 365, "3y": 1095}
    chart_data = {}

    for period_name, days in periods.items():
        nav = get_fund_nav_series_vis(fund_code, days)
        if nav.empty:
            continue
        bench = get_index_data(benchmark_code, days)

        chart_data[period_name] = {
            "dates": nav.index.strftime("%Y-%m-%d").tolist(),
            "fund_nav": normalize_series(nav).round(4).tolist(),
            "bench_nav": normalize_series(bench).round(4).tolist() if not bench.empty else None,
            "fund_return": ((nav.iloc[-1] / nav.iloc[0] - 1) * 100).round(2),
            "bench_return": ((bench.iloc[-1] / bench.iloc[0] - 1) * 100).round(2) if not bench.empty else None,
        }

        df, periods_list = calculate_drawdown_series(nav)
        max_dd = df['drawdown'].min()
        max_period = next((p for p in periods_list if p['max_drawdown'] == max_dd), None)

        recovery_days = 0
        if max_period and not max_period.get('is_active', False):
            recovery_days = (max_period['end'] - max_period['start']).days

        chart_data[period_name].update({
            "max_drawdown": round(max_dd, 2),
            "recovery_days": recovery_days,
            "drawdown_series": df['drawdown'].round(2).tolist(),
            "drawdown_dates": df.index.strftime("%Y-%m-%d").tolist(),
            "dd_start": max_period['start'].strftime("%Y-%m-%d") if max_period else None,
            "dd_end": max_period['end'].strftime("%Y-%m-%d") if max_period else None,
        })

    html_template = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{fund_name} - 基金分析</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f7fa;padding:20px}}
.container{{max-width:1200px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1a3a5c,#2d6a9f);color:#fff;padding:24px 30px;border-radius:12px;margin-bottom:20px}}
.header h1{{font-size:24px;font-weight:600}}
.header .sub{{font-size:14px;opacity:.8;margin-top:6px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}}
.stat-card{{background:#fff;padding:14px 18px;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.stat-card .label{{font-size:12px;color:#889}}
.stat-card .value{{font-size:20px;font-weight:600;margin-top:4px}}
.stat-card .value.positive{{color:#e74c3c}}
.stat-card .value.negative{{color:#27ae60}}
.tabs{{display:flex;gap:4px;background:#fff;padding:6px;border-radius:10px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.tab-btn{{padding:8px 20px;border:none;border-radius:8px;background:transparent;cursor:pointer;font-size:14px;font-weight:500;color:#567;transition:.2s}}
.tab-btn:hover{{background:#f0f2f5}}
.tab-btn.active{{background:#1a3a5c;color:#fff}}
.chart-container{{background:#fff;border-radius:12px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,.06);margin-bottom:16px}}
.chart-box{{width:100%;height:420px}}
.chart-box-small{{height:200px}}
.footer{{text-align:center;color:#9ab;font-size:12px;margin-top:20px;padding:16px}}
@media(max-width:640px){{.header{{padding:16px 20px}}.header h1{{font-size:18px}}.stats{{grid-template-columns:repeat(3,1fr)}}.stat-card{{padding:10px 12px}}.stat-card .value{{font-size:16px}}.tab-btn{{padding:6px 12px;font-size:12px}}.chart-box{{height:300px}}.chart-box-small{{height:150px}}}}
</style>
</head>
<body>
<div class="container">
<div class="header"><h1>📊 {fund_name}</h1><div class="sub">{fund_code} · {fund_type} · 基准:{benchmark_name}</div></div>
<div class="stats" id="stats-container"></div>
<div class="tabs" id="tab-container">
<button class="tab-btn active" data-period="3m">近3月</button>
<button class="tab-btn" data-period="6m">近6月</button>
<button class="tab-btn" data-period="1y">近1年</button>
<button class="tab-btn" data-period="3y">近3年</button>
</div>
<div class="chart-container"><div id="chart-main" class="chart-box"></div></div>
<div class="chart-container"><div id="chart-drawdown" class="chart-box chart-box-small"></div></div>
<div class="footer">数据来源:天天基金 · {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
</div>
<script>
var allData={json.dumps(chart_data,ensure_ascii=False)};
var fundName="{fund_name}",benchName="{benchmark_name}";
var mainChart=echarts.init(document.getElementById('chart-main'));
var ddChart=echarts.init(document.getElementById('chart-drawdown'));

function updateCharts(period){{
var data=allData[period];if(!data)return;
var statsHTML='';
var fundReturn=data.fund_return||0,benchReturn=data.bench_return||0,maxDD=data.max_drawdown||0,recoveryDays=data.recovery_days||0;
statsHTML+='<div class="stat-card"><div class="label">基金收益</div><div class="value '+(fundReturn>=0?'positive':'negative')+'">'+fundReturn+'%</div></div>';
statsHTML+='<div class="stat-card"><div class="label">'+benchName+'收益</div><div class="value '+(benchReturn>=0?'positive':'negative')+'">'+benchReturn+'%</div></div>';
statsHTML+='<div class="stat-card"><div class="label">超额收益</div><div class="value '+((fundReturn-benchReturn)>=0?'positive':'negative')+'">'+(fundReturn-benchReturn).toFixed(2)+'%</div></div>';
statsHTML+='<div class="stat-card"><div class="label">最大回撤</div><div class="value negative">'+maxDD+'%</div></div>';
statsHTML+='<div class="stat-card"><div class="label">回撤修复</div><div class="value neutral">'+recoveryDays+'天</div></div>';
document.getElementById('stats-container').innerHTML=statsHTML;

var dates=data.dates||[],fundNav=data.fund_nav||[],benchNav=data.bench_nav||[];
var series=[{{name:fundName,type:'line',data:fundNav,smooth:true,lineStyle:{{width:2.5,color:'#e74c3c'}},itemStyle:{{color:'#e74c3c'}},areaStyle:{{color:new echarts.graphic.LinearGradient(0,0,0,1,[{{offset:0,color:'rgba(231,76,60,0.25)'}},{{offset:1,color:'rgba(231,76,60,0.02)'}}])}}}}];
if(benchNav&&benchNav.length>0){{series.push({{name:benchName,type:'line',data:benchNav,smooth:true,lineStyle:{{width:2,color:'#3498db',type:'dashed'}},itemStyle:{{color:'#3498db'}}}});}}
mainChart.setOption({{
tooltip:{{trigger:'axis',formatter:function(params){{var html=params[0].axisValue+'<br/>';params.forEach(function(p){{html+=p.marker+' '+p.seriesName+': '+p.value.toFixed(4)+'<br/>';}});return html;}}}},
legend:{{data:[fundName,benchName].filter(function(n){{return n;}}),top:0,left:'center'}},
grid:{{top:50,bottom:50,left:50,right:20}},
xAxis:{{type:'category',data:dates,axisLabel:{{fontSize:11,rotate:dates.length>60?30:0}},splitLine:{{show:false}}}},
yAxis:{{type:'value',min:function(value){{return Math.floor(value.min*0.98*100)/100;}},max:function(value){{return Math.ceil(value.max*1.02*100)/100;}},axisLabel:{{fontSize:11}},splitLine:{{lineStyle:{{color:'#eee',type:'dashed'}}}}}},
series:series,dataZoom:[{{type:'slider',start:0,end:100,height:35,bottom:0}}]
}});

var ddDates=data.drawdown_dates||[],ddValues=data.drawdown_series||[];
ddChart.setOption({{
tooltip:{{trigger:'axis',formatter:function(params){{return params[0].axisValue+'<br/>回撤:'+params[0].value+'%';}}}},
grid:{{top:15,bottom:20,left:50,right:20}},
xAxis:{{type:'category',data:ddDates,axisLabel:{{fontSize:10,rotate:ddDates.length>60?30:0}},splitLine:{{show:false}}}},
yAxis:{{type:'value',max:2,axisLabel:{{fontSize:10,formatter:function(v){{return v+'%';}}}},splitLine:{{lineStyle:{{color:'#eee',type:'dashed'}}}}}},
series:[{{name:'回撤',type:'line',data:ddValues,smooth:true,lineStyle:{{width:1.5,color:'#27ae60'}},itemStyle:{{color:'#27ae60'}},areaStyle:{{color:new echarts.graphic.LinearGradient(0,0,0,1,[{{offset:0,color:'rgba(39,174,96,0.2)'}},{{offset:1,color:'rgba(39,174,96,0.01)'}}])}},markPoint:{{data:[{{type:'min',name:'最大回撤',symbolSize:50}}],label:{{formatter:function(p){{return p.value+'%';}},fontSize:10,fontWeight:'bold'}}}}}}]
}});
setTimeout(function(){{mainChart.resize();ddChart.resize();}},100);
}}
document.querySelectorAll('.tab-btn').forEach(function(tab){{tab.addEventListener('click',function(){{document.querySelectorAll('.tab-btn').forEach(function(t){{t.classList.remove('active');}});this.classList.add('active');updateCharts(this.dataset.period);}});}});
updateCharts('3m');
window.addEventListener('resize',function(){{mainChart.resize();ddChart.resize();}});
</script>
</body>
</html>'''

    if output_path:
        from pathlib import Path
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_template)
        print(f"✅ HTML 报告已生成: {output_path}")
        return output_path

def generate_funds_compare_html(
    fund_codes: List[str],
    benchmark_code: str = "000300",
    output_path: str = None
) -> str:
    """生成多只基金对比的交互式 HTML 报告"""
    if not fund_codes or len(fund_codes) < 2:
        print("⚠️ 至少需要2只基金进行对比")
        return ""

    fund_names = [get_fund_name(code) or code for code in fund_codes]
    benchmark_name = {"000300": "沪深300", "000012": "国债指数"}.get(benchmark_code, benchmark_code)

    periods = {"3m": 90, "6m": 180, "1y": 365, "3y": 1095}
    colors = ['#e74c3c', '#3498db', '#f39c12', '#2ecc71', '#9b59b6', '#1abc9c', '#e67e22', '#e84393']
    chart_data = {}

    for period_name, days in periods.items():
        unified_dates = None
        fund_series_list = []

        for code in fund_codes:
            nav = get_fund_nav_series_vis(code, days)
            if nav.empty:
                continue
            nav_norm = normalize_series(nav)
            dates = nav.index.strftime("%Y-%m-%d").tolist()
            fund_series_list.append({
                "code": code,
                "name": get_fund_name(code) or code,
                "data": nav_norm,
                "dates": dates,
                "return": ((nav.iloc[-1] / nav.iloc[0] - 1) * 100).round(2)
            })
            unified_dates = set(dates) if unified_dates is None else unified_dates.intersection(set(dates))

        if not fund_series_list:
            continue

        bench = get_index_data(benchmark_code, days)
        bench_series = None
        if not bench.empty:
            bench_norm = normalize_series(bench)
            bench_dates = set(bench.index.strftime("%Y-%m-%d").tolist())
            unified_dates = unified_dates.intersection(bench_dates) if unified_dates is not None else bench_dates
            bench_series = {
                "name": benchmark_name,
                "data": bench_norm,
                "dates": bench.index.strftime("%Y-%m-%d").tolist()
            }

        if not unified_dates:
            continue
        unified_dates = sorted(unified_dates)

        period_data = {"dates": unified_dates, "funds": [], "benchmark": None}

        if bench_series:
            bench_dict = dict(zip(bench_series["dates"], bench_series["data"]))
            period_data["benchmark"] = {
                "name": benchmark_name,
                "data": [bench_dict.get(d) for d in unified_dates]
            }

        for i, fs in enumerate(fund_series_list):
            fund_dict = dict(zip(fs["dates"], fs["data"]))
            period_data["funds"].append({
                "code": fs["code"],
                "name": fs["name"],
                "data": [fund_dict.get(d) for d in unified_dates],
                "color": colors[i % len(colors)],
                "return": fs["return"]
            })

        chart_data[period_name] = period_data

    if not chart_data:
        print("⚠️ 没有获取到任何数据")
        return ""

    html_template = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>基金对比分析</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f7fa;padding:20px}}
.container{{max-width:1200px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1a3a5c,#2d6a9f);color:#fff;padding:24px 30px;border-radius:12px;margin-bottom:20px}}
.header h1{{font-size:24px;font-weight:600}}
.header .sub{{font-size:14px;opacity:.8;margin-top:6px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}}
.stat-card{{background:#fff;padding:14px 18px;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.06);border-left:4px solid #ccc}}
.stat-card .label{{font-size:12px;color:#889}}
.stat-card .value{{font-size:20px;font-weight:600;margin-top:4px}}
.stat-card .value.positive{{color:#e74c3c}}
.stat-card .value.negative{{color:#27ae60}}
.tabs{{display:flex;gap:4px;background:#fff;padding:6px;border-radius:10px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.tab-btn{{padding:8px 20px;border:none;border-radius:8px;background:transparent;cursor:pointer;font-size:14px;font-weight:500;color:#567;transition:.2s}}
.tab-btn:hover{{background:#f0f2f5}}
.tab-btn.active{{background:#1a3a5c;color:#fff}}
.chart-container{{background:#fff;border-radius:12px;padding:16px;box-shadow:0 2px 8px rgba(0,0,0,.06);margin-bottom:16px}}
.chart-box{{width:100%;height:500px}}
.footer{{text-align:center;color:#9ab;font-size:12px;margin-top:20px;padding:16px}}
@media(max-width:640px){{.header{{padding:16px 20px}}.header h1{{font-size:18px}}.stats{{grid-template-columns:repeat(2,1fr)}}.stat-card{{padding:10px 12px}}.stat-card .value{{font-size:16px}}.tab-btn{{padding:6px 12px;font-size:12px}}.chart-box{{height:350px}}}}
</style>
</head>
<body>
<div class="container">
<div class="header"><h1>📊 基金对比</h1><div class="sub">{', '.join(fund_names)} · 基准:{benchmark_name}</div></div>
<div class="stats" id="stats-container"></div>
<div class="tabs" id="tab-container">
<button class="tab-btn active" data-period="3m">近3月</button>
<button class="tab-btn" data-period="6m">近6月</button>
<button class="tab-btn" data-period="1y">近1年</button>
<button class="tab-btn" data-period="3y">近3年</button>
</div>
<div class="chart-container"><div id="chart-main" class="chart-box"></div></div>
<div class="footer">数据来源:天天基金 · {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
</div>
<script>
var allData={json.dumps(chart_data,ensure_ascii=False)};
var fundNames={json.dumps(fund_names)};
var fundCodes={json.dumps(fund_codes)};
var colors={json.dumps(colors)};
var benchName="{benchmark_name}";
var mainChart=echarts.init(document.getElementById('chart-main'));

function updateCharts(period){{
var data=allData[period];if(!data)return;
var statsHTML='';
data.funds.forEach(function(fund,i){{
var ret=fund.return||0;var color=colors[i%colors.length];
statsHTML+='<div class="stat-card" style="border-left-color:'+color+'">';
statsHTML+='<div class="label">'+fund.name+'</div>';
statsHTML+='<div class="value '+(ret>=0?'positive':'negative')+'">'+ret+'%</div></div>';
}});
if(data.benchmark&&data.benchmark.data&&data.benchmark.data.length>0){{
var benchData=data.benchmark.data;var first=benchData[0];var last=benchData[benchData.length-1];
var benchRet=(first&&last)?((last/first-1)*100).toFixed(2):'0.00';
statsHTML+='<div class="stat-card" style="border-left-color:#95a5a6"><div class="label">'+data.benchmark.name+'</div>';
statsHTML+='<div class="value '+(parseFloat(benchRet)>=0?'positive':'negative')+'">'+benchRet+'%</div></div>';
}}
document.getElementById('stats-container').innerHTML=statsHTML;

var dates=data.dates||[];var series=[];
data.funds.forEach(function(fund,i){{
var color=colors[i%colors.length];
series.push({{name:fund.name,type:'line',data:fund.data,smooth:true,connectNulls:true,lineStyle:{{width:2.5,color:color}},itemStyle:{{color:color}},areaStyle:{{color:new echarts.graphic.LinearGradient(0,0,0,1,[{{offset:0,color:color+'40'}},{{offset:1,color:color+'05'}}])}}}});
}});
if(data.benchmark&&data.benchmark.data&&data.benchmark.data.length>0){{
series.push({{name:data.benchmark.name,type:'line',data:data.benchmark.data,smooth:true,connectNulls:true,lineStyle:{{width:2,color:'#95a5a6',type:'dashed'}},itemStyle:{{color:'#95a5a6'}}}});
}}
mainChart.setOption({{
tooltip:{{trigger:'axis',formatter:function(params){{var html=params[0].axisValue+'<br/>';params.forEach(function(p){{if(p.value!==null&&p.value!==undefined){{html+=p.marker+' '+p.seriesName+': '+p.value.toFixed(4)+'<br/>';}}}});return html;}}}},
legend:{{data:series.map(function(s){{return s.name;}}),top:0,left:'center',type:'scroll'}},
grid:{{top:60,bottom:50,left:50,right:20}},
xAxis:{{type:'category',data:dates,axisLabel:{{fontSize:11,rotate:dates.length>60?30:0}},splitLine:{{show:false}}}},
yAxis:{{type:'value',min:function(value){{return Math.floor(value.min*0.96*100)/100;}},max:function(value){{return Math.ceil(value.max*1.04*100)/100;}},axisLabel:{{fontSize:11}},splitLine:{{lineStyle:{{color:'#eee',type:'dashed'}}}}}},
series:series,dataZoom:[{{type:'slider',start:0,end:100,height:35,bottom:0}},{{type:'inside',start:0,end:100}}]
}});
setTimeout(function(){{mainChart.resize();}},100);
}}
document.querySelectorAll('.tab-btn').forEach(function(tab){{tab.addEventListener('click',function(){{document.querySelectorAll('.tab-btn').forEach(function(t){{t.classList.remove('active');}});this.classList.add('active');updateCharts(this.dataset.period);}});}});
updateCharts('3m');
window.addEventListener('resize',function(){{mainChart.resize();}});
</script>
</body>
</html>'''

    if output_path:
        from pathlib import Path
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_template)
        print(f"✅ HTML 报告已生成: {output_path}")
        return output_path
