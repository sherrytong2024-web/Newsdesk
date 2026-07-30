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
# 外国：彭博三频道(主) + S&P(Google聚合,主) + CNBC/Investing(次)
# 国内：财联社电报(Google聚合,主) + 财新(Google聚合,次)
SOURCES = [
    {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss", "t": "sec", "per": 8},
    {"name": "Bloomberg Business", "url": "https://feeds.bloomberg.com/business/news.rss", "t": "sec", "per": 8},
    {"name": "Bloomberg Tech", "url": "https://feeds.bloomberg.com/technology/news.rss", "t": "sec", "per": 7},
    {"name": "S&P Global(Google聚合)", "url": "https://news.google.com/rss/search?q=when:7d%20S%26P%20500%20market%20OR%20S%26P%20Global%20economy&hl=en-US&gl=US&ceid=US:en", "t": "sec", "per": 16},
    {"name": "财联社电报(Google聚合)", "url": "https://news.google.com/rss/search?q=when:7d%20site:cls.cn&hl=zh-CN&gl=CN&ceid=CN:zh", "t": "sec", "per": 24},
    {"name": "财新(Google聚合)", "url": "https://news.google.com/rss/search?q=when:7d%20site:caixinglobal.com&hl=en-US&gl=US&ceid=US:en", "t": "sec", "per": 12},
    {"name": "CNBC", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "t": "sec", "per": 12},
    {"name": "Investing.com(综合)", "url": "https://www.investing.com/rss/news.rss", "t": "agg", "per": 14},
    {"name": "Investing.com(商品)", "url": "https://www.investing.com/rss/commodities.rss", "t": "agg", "per": 14},
    {"name": "Investing.com(外汇)", "url": "https://www.investing.com/rss/forex.rss", "t": "agg", "per": 14},
]

# 每类目标条数（4类 × 15 = 60）
CATS_PER = 15
GENERIC = {"股","涨","跌","指数","板块","公司","经济","科技","能源","市场","政策","行业","报告","数据","增长","下跌","上涨"}  # 热值计算中剔除的泛化词
MIN = {  # 可信源最低保底（多样性保障）
    "S&P Global(Google聚合)": 3, "财联社电报(Google聚合)": 3, "财新(Google聚合)": 2,
    "CNBC": 2, "Investing.com(综合)": 2, "Investing.com(商品)": 2,
}

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
    """按命中关键词数量最多的类别归类（避免 global 被前面的类别饿死）"""
    t = (title + " " + summary).lower()
    best, best_n = None, 0
    for cat in ("macro", "stock", "sector", "global"):
        n = sum(1 for k in KW[cat] if k.lower() in t)
        if n > best_n:
            best, best_n = cat, n
    return best  # None 表示未命中任何金融分类 → 丢弃


def topic_sig(title, summary, cat):
    """提取话题签名：类别关键词中"非泛化"的命中词，用于跨源交叉印证"""
    t = (title + " " + summary).lower()
    return {k.lower() for k in KW[cat] if k.lower() in t and k not in GENERIC}


def compute_heat(items):
    """热度指数计算标准（系统内部保留，前端 HEAT_STANDARD 与注释同步）

    热度 = 跨源印证分 + 信源等级分 + 时效分
      · 跨源印证分 = 与本条共享「非泛化金融关键词」的其他新闻条数 × 4
          同一事件被越多独立信源报道越热（模拟微博跨源热议）
      · 信源等级分 = 一手/媒体(sec) = 2；聚合平台(agg) = 1
      · 时效分     = max(0, (48 − t)) / 48 × 8，其中 t 为发布距现在的小时数
          刚发布 8 分，24h 后 4 分，48h 及以上 0 分（线性衰减）
    结果四舍五入保留 1 位小数。该标准同时写进前端 HEAT_STANDARD 常量，便于核验。
    """
    now = datetime.now(timezone(timedelta(hours=8)))
    for it in items:
        it["_sig"] = topic_sig(it["title"], it["summary"], it["cat"])
    for it in items:
        try:
            if len(it["time"]) > 10:
                dt = datetime.strptime(it["time"], "%Y-%m-%d %H:%M")
            else:
                dt = datetime.strptime(it["time"], "%Y-%m-%d")
            dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
        except Exception:
            dt = now
        hours = (now - dt).total_seconds() / 3600
        recency = max(0.0, (48 - hours)) / 48 * 8.0  # 0~8
        cross = sum(1 for o in items if o is not it and (it["_sig"] & o["_sig"]))
        tier = 2 if it["srcs"][0]["t"] == "sec" else 1
        it["heat"] = round(cross * 4 + tier * 2 + recency, 1)


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
            for suf in ("Caixin Global", "财联社", "cls.cn", "S&P Global", "bloomberg.com", "Bloomberg", "Reuters", "Investing.com", "CNBC", "WSJ", "The Wall Street Journal"):
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
    if os.environ.get("NEWSDESK_NO_PUSH"):
        sys.stderr.write("[INFO] 跳过本地 git 推送（由 CI/工作流负责）\n")
        return
    try:
        subprocess.run(["git", "-C", workdir, "add", "news.json", "hot.json", "financial-news-desk.html", "archive", "index.html", "update_news.py", ".github/workflows/refresh.yml"],
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
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args()

    # 1) 全量拉取（单源上限防霸屏，黑名单+分类已在前置过滤）
    all_items = []
    seen = set()
    src_counts = {}
    MAX_PER = 24
    for src in SOURCES:
        for it in fetch_feed(src):
            key = it["title"].strip().lower()
            if key in seen or not it["srcs"][0]["u"]:
                continue
            if src_counts.get(src["name"], 0) >= MAX_PER:
                continue
            seen.add(key)
            src_counts[src["name"]] = src_counts.get(src["name"], 0) + 1
            all_items.append(it)

    if not all_items:
        sys.stderr.write("[WARN] 所有源均无返回，保留上次数据\n")
        return

    # 2) 计算热值
    compute_heat(all_items)

    # 3) 每类取热值最高的 15 条（用户要求每类15条，共60）
    cats = {c: [] for c in ("macro", "sector", "stock", "global")}
    for it in all_items:
        cats[it["cat"]].append(it)
    final = []
    for c in ("macro", "sector", "stock", "global"):
        lst = sorted(cats[c], key=lambda x: x["heat"], reverse=True)
        final.extend(lst[:CATS_PER])

    # 4) 多样性保底：确保每个可信源至少出现
    pool = [it for it in all_items if it not in final]
    for src, mn in MIN.items():
        have = sum(1 for it in final if it["srcs"][0]["n"] == src)
        if have >= mn:
            continue
        for it in sorted(pool, key=lambda x: x["heat"], reverse=True):
            if it["srcs"][0]["n"] == src:
                # 用最弱的非保底 final 项交换
                victim = min((x for x in final if x["srcs"][0]["n"] not in MIN),
                             key=lambda x: x["heat"])
                final.remove(victim)
                final.append(it)
                pool.remove(it)
                if sum(1 for x in final if x["srcs"][0]["n"] == src) >= mn:
                    break

    # 清理内部字段
    for it in final:
        it.pop("_sig", None)

    # 5) 注入 HTML（按类内热值降序）
    news_js = ",\n".join(json.dumps(it, ensure_ascii=False) for it in final)

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

    # 6) 生成 news.json（前端动态加载）
    out_dir = os.path.dirname(os.path.abspath(args.out))
    payload = {"updated": ts, "items": final}
    with open(os.path.join(out_dir, "news.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    # 7) 生成 hot.json（微博式热点榜：全量热值 Top10）
    hot = sorted(final, key=lambda x: x["heat"], reverse=True)[:10]
    with open(os.path.join(out_dir, "hot.json"), "w", encoding="utf-8") as f:
        json.dump({"updated": ts, "items": hot}, f, ensure_ascii=False, indent=1)

    # 8) 按天归档（保留最近 7 天，支撑"每日热点"对比）
    adir = os.path.join(out_dir, "archive")
    os.makedirs(adir, exist_ok=True)
    aday = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    with open(os.path.join(adir, f"{aday}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    for fn in sorted(os.listdir(adir))[:-7]:
        try:
            os.remove(os.path.join(adir, fn))
        except OSError:
            pass

    # 9) 推送
    git_commit_push(out_dir, f"update news {ts}")

    # 统计
    by_cat = {}
    for it in final:
        by_cat[it["cat"]] = by_cat.get(it["cat"], 0) + 1
    print(f"[OK] 已生成 {len(final)} 条新闻 -> {args.out}")
    print(f"     分类: {by_cat}")
    print(f"     热值区间: {min(it['heat'] for it in final):.1f} ~ {max(it['heat'] for it in final):.1f}")
    print(f"     更新时间: {ts}")


if __name__ == "__main__":
    main()
