#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全球金融新闻台 · 本地自动更新脚本（零依赖，仅标准库）

功能：
  从多个独立 RSS 源拉取真实新闻，解析、去重、分类，
  注入已生成的 financial-news-desk.html（复用其 UI），每条附真实可点击来源。

设计原则（回应"来源虚假"问题）：
  - 全部为一手/二手媒体真实 RSS，不依赖腾讯系聚合器
  - 每条新闻保留原始 link，可点击核验
  - 信源等级：sec=媒体(含官媒) / agg=聚合平台

用法：
  python3 update_news.py                  # 生成到同目录 financial-news-desk.html
  python3 update_news.py --out /path/x.html
  python3 update_news.py --limit 40

定时（macOS/Linux crontab，每 3 小时）：
  0 */3 * * * /usr/bin/python3 /你的路径/update_news.py >> /tmp/newsdesk.log 2>&1

数据源（已探测可达，2026-07-30）：
  新华社 / 人民日报财经（国内官媒）
  CNBC / WSJ（国际媒体）
  Investing.com 综合 & 商品（聚合平台）
单源失败不影响其余源。
"""

import urllib.request
import ssl
import xml.etree.ElementTree as ET
import email.utils
import json
import re
import sys
import os
import argparse
import subprocess
from datetime import datetime, timezone, timedelta

UA = "Mozilla/5.0 (compatible; NewsDeskBot/1.0)"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# 源配置：name 展示名, url RSS地址, t 信源等级(sec/agg), per 每源取条数
# 国内：新华社/人民日报财经(官媒) + 财新(Google聚合)  国际：CNBC/Bloomberg三频道/Investing/WSJ(容错)
SOURCES = [
    {"name": "新华社财经", "url": "http://www.xinhuanet.com/fortune/news_fortune.xml", "t": "sec", "per": 0},
    {"name": "人民日报财经", "url": "http://www.people.com.cn/rss/finance.xml", "t": "sec", "per": 0},
    {"name": "财新(Google聚合)", "url": "https://news.google.com/rss/search?q=when:24h%20site:caixinglobal.com&hl=en-US&gl=US&ceid=US:en", "t": "sec", "per": 10},
    {"name": "CNBC", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "t": "sec", "per": 8},
    {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss", "t": "sec", "per": 10},
    {"name": "Bloomberg Business", "url": "https://feeds.bloomberg.com/business/news.rss", "t": "sec", "per": 10},
    {"name": "Bloomberg Tech", "url": "https://feeds.bloomberg.com/technology/news.rss", "t": "sec", "per": 10},
    {"name": "Investing.com(综合)", "url": "https://www.investing.com/rss/news.rss", "t": "agg", "per": 8},
    {"name": "Investing.com(商品)", "url": "https://www.investing.com/rss/commodities.rss", "t": "agg", "per": 6},
    {"name": "WSJ", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "t": "sec", "per": 10},
]

# 黑名单：命中任一词 → 直接丢弃（非金融噪音）
BLACKLIST = [
    # 医疗/防疫
    "新冠","新冠病毒","疫情防控","疫苗","接种","确诊","感染病毒","阳性","阴性",
    "核酸检测","隔离","口罩","抗疫","防疫","流行病","传染病","病例",
    "心血管病","患者一旦","基础病症","医院常务","打疫苗",
    # 体育/娱乐
    "奥运","世界杯","NBA","CBA","球队","夺冠","明星","演唱会","票房","综艺","体育精神","赛事","联赛","金牌","银牌","铜牌","冠军",
    # 社会/民生（无金融关联）
    "高温预警","暴雨","台风","地震","火灾","事故","伤亡","失踪","寻人",
    "招生","高考","中考","开学","寒假","暑假","放假",
    # 其他纯社会/弱公关
    "好人好事","感动","暖心","点赞","网友热议","热搜","刷屏",
    "赋能","品质提升","稳就业","促消费作用","行业发展质量实现","认证认可检验检测",
]

# 分类关键词（中英文混合）；只保留强金融信号词，已剔除过于宽泛的"政策""经济""公司"
KW = {
    "macro": ["美联储","央行","联储","利率","降息","加息","通胀","货币","财政","政治局会议","gdp","tariff","关税","逆周期调节","fomc","联邦基金","公开市场","存款准备金","mlf","lpr","国债","赤字","财政政策","货币政策","量化宽松","qe","缩表","rate","rates","fed","inflation","yields","yield","treasury","ecb","boe","boj","pboc","stimulus","budget","deficit","监管","证监会","纾困","复工复产","稳增长","普惠金融"],
    "stock": ["股","涨","跌","指数","板块","营收","净利","ipo","回购","涨停","跌停","stock","shares","earnings","财报","市值","估值","市盈率","成交量","融资余额","北向资金","南向资金","港股通","沪深","上证","深证","创业板","科创板","ETF","基金","分红","除权","除息","举牌","增持","减持","并购","重组","借壳","退市","st股","龙头","主力资金","散户","机构","游资"],
    "sector": ["ai","人工智能","芯片","半导体","新能源","电池","光伏","汽车","机器人","算力","医药","消费","银行","房地产","科技","能源","nvidia","tesla","apple","chip","大模型","锂电","储能","风电","核电","白酒","家电","军工","航空","航运","港口","铁路","基建","5g","6g","云计算","数据中心","互联网","电商","快递","物流","农业","粮食","猪肉","生猪","铜","铝","稀土","矿产"],
    "global": ["原油","黄金","美债","美元","地缘","欧洲","日本","韩国","港股","美股","oil","gold","bond","dollar","crude","brent","比特币","btc","加密货币","以太坊","汇率","人民币","日元","欧元","英镑","日经","道琼斯","标普","纳斯达克","恒生","富时","欧股","亚太","美联储","欧央行","日央行","英央行"],
}


def localname(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def find_child(el, name):
    for c in el.iter():
        if localname(c.tag) == name:
            return c
    return None


def strip_tags(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_date(s):
    if not s:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=8)))
    except Exception:
        # 尝试 ISO 格式
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s[:len(fmt)+3], fmt).replace(tzinfo=timezone(timedelta(hours=8)))
            except Exception:
                continue
    return None


def is_finance_related(title, summary):
    """黑名单硬过滤：命中非金融关键词直接丢弃"""
    t = title + " " + summary
    for kw in BLACKLIST:
        if kw.lower() in t.lower():
            return False
    return True


def classify(title, summary):
    t = (title + " " + summary).lower()
    for cat in ("macro", "stock", "sector", "global"):
        if any(k.lower() in t for k in KW[cat]):
            return cat
    return None  # 未命中任何金融分类 → 丢弃


def fetch_feed(src):
    out = []
    try:
        req = urllib.request.Request(src["url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
            data = r.read()
        root = ET.fromstring(data)
        nodes = [el for el in root.iter() if localname(el.tag) in ("item", "entry")]
        for it in nodes[: src["per"]]:
            title_el = find_child(it, "title")
            title = strip_tags(title_el.text if title_el is not None else "")
            if not title:
                continue
            # 清理 Google News 聚合标题后缀（如 " - Caixin Global" / " - bloomberg.com"）
            for suf in ("Caixin Global", "bloomberg.com", "Bloomberg", "Reuters", "Investing.com", "CNBC", "WSJ", "The Wall Street Journal"):
                if title.endswith(" - " + suf):
                    title = title[: -(len(suf) + 3)].strip()
                    break
            # link: RSS 用 <link> 文本; Atom 用 <link href>
            link = ""
            link_el = find_child(it, "link")
            if link_el is not None:
                link = (link_el.get("href") or link_el.text or "").strip()
            desc_el = None
            for n in ("description", "summary", "content"):
                desc_el = find_child(it, n)
                if desc_el is not None:
                    break
            summary = strip_tags(desc_el.text if desc_el is not None else "")
            summary = summary[:180] + ("…" if len(summary) > 180 else "")
            date_el = None
            for n in ("pubDate", "updated", "published"):
                date_el = find_child(it, n)
                if date_el is not None:
                    break
            dt = parse_date(date_el.text if date_el is not None else "")
            time_str = dt.strftime("%Y-%m-%d %H:%M") if dt else datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            link = link.replace("<", "").replace(">", "")
            # 前置过滤：黑名单 + 金融相关性
            if not is_finance_related(title, summary):
                continue
            cat = classify(title, summary)
            if cat is None:
                continue  # 未命中任何金融分类，丢弃
            out.append({
                "cat": cat,
                "time": time_str,
                "title": title[:120],
                "summary": summary,
                "srcs": [{"n": src["name"], "u": link, "t": src["t"]}],
            })
    except Exception as e:
        sys.stderr.write(f"[WARN] 源 {src['name']} 拉取失败: {type(e).__name__}: {str(e)[:80]}\n")
    return out


def replace_news_block(html, news_js):
    lines = html.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("let NEWS = [") or ln.strip().startswith("const NEWS = ["):
            start = i
            break
    if start is None:
        raise RuntimeError("未在 HTML 中找到 'const NEWS = [' 标记，无法注入数据")
    end = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "];":
            end = i
            break
    if end is None:
        raise RuntimeError("未找到 NEWS 数组结束 '];'")
    block = "let NEWS = [\n" + news_js + "\n];"
    return "\n".join(lines[:start] + [block] + lines[end + 1:])


def replace_time(html, ts):
    return re.sub(r"数据快照 [0-9:\- ]+ \(GMT\+8\)", f"数据快照 {ts} (GMT+8)", html)


def git_commit_push(workdir, msg):
    """若当前目录是 git 仓库且已配置 remote，则自动提交并推送。失败不影响本地文件。"""
    try:
        subprocess.run(["git", "-C", workdir, "add", "news.json", "financial-news-desk.html"],
                       check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "-C", workdir, "commit", "-m", msg],
                       check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "-C", workdir, "push"],
                       check=True, capture_output=True, timeout=90)
        sys.stderr.write("[OK] 已推送到 GitHub（公网自动更新）\n")
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", "ignore")[:120] if e.stderr else ""
        sys.stderr.write(f"[WARN] git 推送跳过（未配置仓库/无变化/需先 setup）: {err}\n")
    except FileNotFoundError:
        sys.stderr.write("[WARN] 未找到 git 命令，跳过推送\n")


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--out", default=os.path.join(here, "financial-news-desk.html"))
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    all_items = []
    seen = set()
    for src in SOURCES:
        for it in fetch_feed(src):
            key = it["title"].strip().lower()
            if key in seen or not it["srcs"][0]["u"]:
                continue
            seen.add(key)
            all_items.append(it)
            if len(all_items) >= args.limit * 2:
                break
        if len(all_items) >= args.limit * 2:
            break

    all_items.sort(key=lambda x: x["time"], reverse=True)
    all_items = all_items[: args.limit]

    # 生成 JS 对象字面量（json.dumps 输出与 JS 兼容）
    news_js = ",\n".join(json.dumps(it, ensure_ascii=False) for it in all_items)

    if not os.path.exists(args.out):
        sys.stderr.write(f"[ERROR] 目标 HTML 不存在: {args.out}\n请先部署 financial-news-desk.html\n")
        sys.exit(1)

    with open(args.out, "r", encoding="utf-8") as f:
        html = f.read()
    html = replace_news_block(html, news_js)
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    html = replace_time(html, ts)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)

    # 生成 news.json（供前端 fetch 动态加载，使"立即刷新"真正拉取新数据）
    out_dir = os.path.dirname(os.path.abspath(args.out))
    news_json = os.path.join(out_dir, "news.json")
    with open(news_json, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=1)

    # 推送到 GitHub（若已配置仓库）；失败不影响本地文件
    git_commit_push(out_dir, f"update news {ts}")

    # 统计
    by_cat = {}
    for it in all_items:
        by_cat[it["cat"]] = by_cat.get(it["cat"], 0) + 1
    print(f"[OK] 已生成 {len(all_items)} 条新闻 -> {args.out}")
    print(f"     分类: {by_cat}")
    print(f"     更新时间: {ts}")


if __name__ == "__main__":
    main()
