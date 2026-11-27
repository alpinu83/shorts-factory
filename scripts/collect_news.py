"""최근 1~2일 국내 정치 기사 중 관심 높은 것을 후보로 골라 CEO Hub로 전달.

후보는 항상 '언론 기사'(제목·원문 링크·언론사)이고, 다른 유튜브 채널 영상은 후보·출처로 쓰지 않음.
관심도(기사 조회수는 포털이 자동 수집을 금지해 직접 가져올 수 없음)는 허용된 공식 경로 세 가지로 추정:
  1) 보도량: 구글 뉴스 RSS에서 같은 이슈를 다룬 언론사 수
  2) 검색 관심도: 구글 트렌드 한국 인기 검색 RSS의 검색량
  3) 화제도: YouTube 인기 동영상(뉴스·정치) 중 같은 이슈 영상의 조회수 (신호로만, 영상은 쓰지 않음)
비밀값은 환경변수로만 받고 출력하지 않음.
"""
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (X11; Linux x86_64) CEO-Shorts/1.0 (+https://alpinu83.github.io/shorts-factory/)"
MAX_AGE = timedelta(hours=48)
NOW = datetime.now(timezone.utc)
# 국내 정치 판별
POLITICS = re.compile(r"국회|대통령|대통령실|용산|정부|여당|야당|여야|민주당|더불어민주당|국민의힘|국힘|조국혁신당|개혁신당|진보당|정당|의원|원내|당대표|최고위|선거|대선|총선|지선|지방선거|공천|탄핵|특검|검찰|헌재|헌법|개헌|장관|총리|국무|청문회|국정|법안|입법|예산안|지지율|여론조사|북한|안보|국방|비대위|당권")
# 해외 정치만 다루는 기사 제외용
FOREIGN_ONLY = re.compile(r"^(美|미국|中|중국|日|일본|러시아|우크라|이스라엘|이란|EU|유럽|트럼프|바이든|시진핑|푸틴|네타냐후)")


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def clean_title(t):
    return re.sub(r"\s*-\s*[^-]{1,30}$", "", (t or "").strip())


STOP = {"속보", "단독", "종합", "영상", "오늘", "뉴스", "포토"}


def tokens(s):
    return {w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", clean_title(s)) if w not in STOP}


def fresh(pub):
    try:
        dt = parsedate_to_datetime(pub)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return NOW - dt <= MAX_AGE, dt.isoformat()
    except Exception:  # noqa: BLE001
        return False, ""


def google_news():
    queries = ["정치", "국회", "대통령실", "국민의힘", "더불어민주당", "특검", "여야"]
    seen, items = set(), []
    for q in queries:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": f"{q} when:2d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        try:
            root = ET.fromstring(get(url))
        except Exception as e:  # noqa: BLE001
            print(f"google_news skipped({q}): {type(e).__name__}")
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            if not title or link in seen:
                continue
            ok, iso = fresh(it.findtext("pubDate") or "")
            if not ok:
                continue
            ct = clean_title(title)
            if not POLITICS.search(ct) or (FOREIGN_ONLY.search(ct) and not re.search(r"한국|韓|우리|국내|정부|대통령실", ct)):
                continue
            seen.add(link)
            src = it.find("source")
            items.append({"title": ct, "url": link, "source": (src.text if src is not None else "") or "", "publishedAt": iso})
    # 같은 이슈 묶기 → 보도량 = 서로 다른 언론사 수
    clusters = []
    for n in items:
        tk = tokens(n["title"])
        for c in clusters:
            inter = len(tk & c["tk"])
            if inter >= 3 or (tk and inter / max(1, min(len(tk), len(c["tk"]))) >= 0.5):
                c["items"].append(n)
                c["tk"] |= tk
                break
        else:
            clusters.append({"tk": set(tk), "items": [n]})
    for c in clusters:
        c["coverage"] = len({x["source"] or x["url"] for x in c["items"]})
    return clusters


def google_trends():
    """구글 트렌드 한국 인기 검색 (공식 RSS): 검색량과 관련 기사"""
    try:
        root = ET.fromstring(get("https://trends.google.com/trending/rss?geo=KR"))
    except Exception as e:  # noqa: BLE001
        print(f"google_trends skipped: {type(e).__name__}")
        return []
    ns = {"ht": "https://trends.google.com/trending/rss"}
    out = []
    for it in root.iter("item"):
        traffic = it.findtext("ht:approx_traffic", default="", namespaces=ns) or ""
        vol = int(re.sub(r"[^0-9]", "", traffic) or 0)
        news = [{"title": clean_title(n.findtext("ht:news_item_title", default="", namespaces=ns)), "url": n.findtext("ht:news_item_url", default="", namespaces=ns), "source": n.findtext("ht:news_item_source", default="", namespaces=ns)} for n in it.findall("ht:news_item", ns)]
        text = " ".join([it.findtext("title") or ""] + [n["title"] for n in news])
        if POLITICS.search(text):
            out.append({"query": it.findtext("title") or "", "volume": vol, "news": news, "tk": tokens(text)})
    return out


def youtube_popular():
    key = os.environ.get("YT_API_KEY", "").strip()
    if not key:
        return []
    q = urllib.parse.urlencode({"part": "snippet,statistics", "chart": "mostPopular", "regionCode": "KR", "videoCategoryId": "25", "maxResults": 50, "key": key})
    try:
        data = json.loads(get("https://www.googleapis.com/youtube/v3/videos?" + q))
    except Exception as e:  # noqa: BLE001
        print(f"youtube_popular skipped: {type(e).__name__}")
        return []
    return [{"views": int(it.get("statistics", {}).get("viewCount", 0) or 0), "tk": tokens(it["snippet"].get("title", ""))} for it in data.get("items", [])]


def main():
    clusters = google_news()
    trends = google_trends()
    yt = youtube_popular()
    cands = []
    for c in clusters:
        tk = c["tk"]
        tr = max((t for t in trends if len(tk & t["tk"]) >= 2), key=lambda t: t["volume"], default=None)
        yv = max((v["views"] for v in yt if len(tk & v["tk"]) >= 2), default=0)
        head = sorted(c["items"], key=lambda x: x["publishedAt"], reverse=True)[0]
        score = c["coverage"] * 10 + (math.log10(tr["volume"]) * 12 if tr and tr["volume"] else 0) + (math.log10(yv) * 6 if yv else 0)
        cands.append({
            "kind": "news",
            "title": head["title"],
            "url": head["url"],
            "source": head["source"],
            "publishedAt": head["publishedAt"],
            "coverage": c["coverage"],
            "trends": {"query": tr["query"], "volume": tr["volume"]} if tr else None,
            "signal": {"youtubeViews": yv} if yv else None,
            "related": [{"title": x["title"], "url": x["url"], "source": x["source"]} for x in c["items"] if x is not head][:4],
            "score": round(score, 1),
        })
    cands.sort(key=lambda x: x["score"], reverse=True)
    items = cands[:12]
    print(json.dumps({"articles_48h": sum(len(c["items"]) for c in clusters), "issues": len(clusters), "trends_politics": len(trends), "youtube": len(yt), "sent": len(items)}, ensure_ascii=False))
    for x in items[:6]:
        print(f"  {x['score']:>5} | 보도 {x['coverage']} | 검색 {x['trends']['volume'] if x['trends'] else '-'} | 화제 {x['signal']['youtubeViews'] if x['signal'] else '-'} | {x['title'][:50]} ({x['source']})")
    if not items:
        sys.exit("최근 48시간 국내 정치 기사 후보가 없습니다.")
    hub = os.environ.get("HUB_URL", "https://ai-ceo-hub.onrender.com").rstrip("/")
    token = os.environ.get("SHORTS_HOOK_TOKEN", "").strip()
    if not token:
        sys.exit("SHORTS_HOOK_TOKEN이 없어 CEO Hub로 보내지 못했습니다.")
    body = json.dumps({"batch": os.environ.get("BATCH", ""), "items": items}).encode()
    req = urllib.request.Request(f"{hub}/api/shorts/hook/candidates", data=body, method="POST", headers={"Content-Type": "application/json", "x-shorts-token": token, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        print("HUB_RESULT " + r.read().decode()[:300])


if __name__ == "__main__":
    main()
