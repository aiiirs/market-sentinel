#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,logging,os,time,tomllib
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
SYMBOLS={"标普 500":"^GSPC","纳斯达克 100":"^NDX","VIX":"^VIX","VXN":"^VXN"}; LOG=logging.getLogger("us_temperature")
def load(p):
 r=tomllib.loads(p.read_text());s,c=r["schedule"],r["cycle"];return ZoneInfo(s["timezone"]),int(s["hour"]),int(s["minute"]),int(s["poll_seconds"]),bool(s.get("send_enabled",True)),c
def hist(symbol):
 r=requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",params={"period1":473385600,"period2":int(time.time())+86400,"interval":"1d"},headers={"User-Agent":"FeishuSync/1.0"},timeout=20);r.raise_for_status();x=r.json()["chart"]["result"][0];return [(datetime.fromtimestamp(t,timezone.utc).date(),float(v)) for t,v in zip(x["timestamp"],x["indicators"]["quote"][0]["close"]) if v is not None]
def previous_cycle(x,threshold,recovery):
 peak=x[0];active=None;done=[]
 for p in x[1:]:
  if not active:
   if p[1]>=peak[1]:peak=p
   elif p[1]/peak[1]-1<=-threshold:active={"p":peak,"t":p}
  else:
   if p[1]<active["t"][1]:active["t"]=p
   if p[1]>=active["p"][1]*recovery:active["r"]=p;done.append(active);active=None;peak=p
 return done[-1] if done else None
def fgi(day=None):
 try:
  url="https://production.dataviz.cnn.io/index/fearandgreed/graphdata" + (f"/{day}" if day else "")
  x=requests.get(url,headers={"User-Agent":"FeishuSync/1.0"},timeout=20).json()["fear_and_greed"]
  if day and not str(x.get("timestamp","")).startswith(str(day)):return "暂不可用（来源未返回该日数据）"
  score=float(x['score']);return f"{score:.0f}｜{fgi_stage(score)}"
 except Exception:return "暂不可用（不以旧值替代）"
def fgi_stage(score):
 if score<25:return "极度恐惧"
 if score<45:return "恐惧"
 if score<=55:return "中性"
 if score<=75:return "贪婪"
 return "极度贪婪"
def at_or_before(series,day):
 return next((point for point in reversed(series) if point[0]<=day),None)
def stage(value,name):
 limits=(15,20,30,40) if name=="VIX" else (18,25,30,40)
 labels=("平静","中性","紧张","高波动","恐慌")
 for limit,label in zip(limits,labels):
  if value<limit:return label
 return labels[-1]
def main():
 p=argparse.ArgumentParser();p.add_argument("--config",type=Path);p.add_argument("--preview",action="store_true");a=p.parse_args();zone,h,m,poll,enabled,c=load(a.config);state=Path("data/us_market_temperature_state.json");state.parent.mkdir(exist_ok=True);last=json.loads(state.read_text()) if state.exists() else {}
 while True:
  now=datetime.now(zone)
  if a.preview or ((now.hour,now.minute)>=(h,m) and last.get("attempt")!=str(now.date())):
   last["attempt"]=str(now.date());state.write_text(json.dumps(last))
   try:
    data={k:hist(v) for k,v in SYMBOLS.items()};day=str(data["标普 500"][-1][0])
    if a.preview or last.get("sent")!=day:
     lines=[f"**美股收盘日：** {day}","", "**指数行情**"]
     cycles={}
     for n,key in (("标普 500","sp500_threshold"),("纳斯达克 100","nasdaq100_threshold")):
      x=data[n];v,old=x[-1][1],x[-2][1];lines.append(f"- **{n.replace(' ', '')}：** {v:,.2f}（{v/old-1:+.2%}）")
      z=previous_cycle(x,float(c[key]),float(c["recovery_ratio"]));
      cycles[n]=z
      if z:lines += [f"- 上轮大跌幅度：{z['t'][1]/z['p'][1]-1:.2%}（{z['t'][0]:%Y-%m}）",f"- 当前距上一轮前高：{v/z['p'][1]-1:+.2%}",f"- 距离历史高点：{v/max(q[1] for q in x)-1:.2%}"]
     lines += ["", "**波动与情绪**"]
     for n in ("VIX","VXN"):
      x=data[n];lines.append(f"**{n}：** {x[-1][1]:.2f}（{x[-1][1]/x[-2][1]-1:+.2%}）｜当前：{stage(x[-1][1],n)}")
     lines += ["- VIX / VXN 越低：市场越平静、风险偏好通常更高；越高：避险需求与恐慌通常更强。"]
     seen_low_dates=set()
     low_fgi_refs=[]
     for name,z in cycles.items():
      if z:
       low=z["t"][0];vix=at_or_before(data["VIX"],low);vxn=at_or_before(data["VXN"],low)
       if low not in seen_low_dates:
        lines.append(f"- 上一轮低点情绪（{low:%Y-%m}）：VIX {vix[1]:.2f}（{stage(vix[1],'VIX')}）｜VXN {vxn[1]:.2f}（{stage(vxn[1],'VXN')}）")
        low_fgi_refs.append((low,fgi(low)))
        seen_low_dates.add(low)
     lines += ["",f"**CNN Fear & Greed：** {fgi()}","- CNN F&G 越低：市场情绪越恐惧；越高：市场情绪越贪婪."]
     for low,reference in low_fgi_refs:
      if not reference.startswith("暂不可用"):lines.append(f"- 上一轮低点情绪参考（{low:%Y-%m}）：CNN F&G {reference}")
     lines += ["",f"生成时间：{now:%Y-%m-%d %H:%M}（新加坡时间）"]
     card={"msg_type":"interactive","card":{"header":{"title":{"tag":"plain_text","content":"MarketSentinel · 美股温度日报"},"template":"blue"},"elements":[{"tag":"markdown","content":"\n".join(lines)}]}}
     if a.preview:
      print(card["card"]["elements"][0]["content"]);return
     if enabled:
      r=requests.post(os.environ["US_MARKET_TEMPERATURE_FEISHU_WEBHOOK"],json=card,timeout=20);r.raise_for_status();last["sent"]=day;state.write_text(json.dumps(last));Path("data/latest_report.json").write_text(json.dumps(card,ensure_ascii=False,indent=2))
   except Exception:LOG.exception("日报失败")
  time.sleep(max(30,poll))
if __name__=="__main__":main()
