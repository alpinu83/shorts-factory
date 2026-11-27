"""조회수 높은 정치 뉴스 후보 수집 → CEO Hub로 전달.

- YouTube 인기 동영상(뉴스·정치 분야, 한국): YT_API_KEY가 있을 때 조회수와 함께
- 구글 뉴스(한국어) 최근 1일 정치 기사: 키 없이, 같은 이슈를 다룬 언론 수(보도량)로 순위
비밀값은 환경변수로만 받고 출력하지 않음.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (X11; Linux x86_64) CEO-Shorts/1.0 (+https://alpinu83.github.io/shorts-factory/)"
POLITICS = re.compile(r"국회|대통령|대통|정부|여당|야당|민주당|국민의힘|국힘|조국|개혁신당|선거|탄핵|장관|총리|정책|법안|특검|검찰|외교|북한|안보|국정|청와대|용산|의원|정당|여야|헌법|개헌|공천|지지율|여론조사|대선|총선|지선")


def get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def tokens(s):
    s = re.sub(r"\s*-\s*[^-]{1,30}$", "", s)
    return {w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", s)}


def youtube_popular():
    key = os.environ.get("YT_API_KEY", "").strip()
    if not key:
        return []
    q = urllib.parse.urlencode({"part": "snippet,statistics", "chart": "mostPopular", "regionCode": "KR", "videoCategoryId": "25", "maxResults": 30, "key": key})
    try:
        data = json.loads(get("https://www.googleapis.com/youtube/v3/videos?" + q))
    except Exception as e:  # noqa: BLE001
        print(f"youtube_popular skipped: {type(e).__name__}")
        return []
    out = []
    for it in data.get("items", []):
        sn = it.get("snippet", {})
        out.append({
            "kind": "youtube",
            "title": sn.get("title", ""),
            "source": sn.get("channelTitle", ""),
            "url": f"https://www.youtube.com/watch?v={it.get('id')}",
            "views": int(it.get("statistics", {}).get("viewCount", 0) or 0),
            "publishedAt": sn.get("publishedAt", ""),
            "summary": (sn.get("description") or "")[:200],
        })
    return out


def google_news():
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": "정치 when:1d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    try:
        root = ET.fromstring(get(url))
    except Exception as e:  # noqa: BLE001
        print(f"google_news skipped: {type(e).__name__}")
        return []
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = it.find("source")
        items.append({"title": title, "url": (it.findtext("link") or "").strip(), "source": (src.text if src is not None else "") or "", "publishedAt": it.findtext("pubDate") or ""})
    # 같은 이슈 묶기 (제목 단어 겹침)
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
    clusters.sort(key=lambda c: len(c["items"]), reverse=True)
    out = []
    for c in clusters[:20]:
        head = c["items"][0]
        out.append({
            "kind": "news",
            "title": re.sub(r"\s*-\s*[^-]{1,30}$", "", head["title"]),
            "source": head["source"],
            "url": head["url"],
            "coverage": len(c["items"]),
            "publishedAt": head["publishedAt"],
            "related": [{"title": x["title"], "url": x["url"], "source": x["source"]} for x in c["items"][1:5]],
        })
    return out


def main():
    yt = youtube_popular()
    news = google_news()
    pol_yt = [v for v in yt if POLITICS.search(v["title"])]
    yt_sel = sorted(pol_yt if len(pol_yt) >= 3 else yt, key=lambda v: v["views"], reverse=True)[:8]
    # 유튜브 이슈에 관련 기사 붙이기 (출처 확인용)
    for v in yt_sel:
        tk = tokens(v["title"])
        rel = [n for n in news if len(tk & tokens(n["title"])) >= 2][:3]
        v["related"] = [{"title": n["title"], "url": n["url"], "source": n["source"]} for n in rel]
    news_sel = [n for n in news if POLITICS.search(n["title"])][:10] or news[:10]
    items = yt_sel + news_sel
    print(json.dumps({"youtube": len(yt), "youtube_selected": len(yt_sel), "news_clusters": len(news), "news_selected": len(news_sel)}, ensure_ascii=False))
    if not items:
        sys.exit("수집된 후보가 없습니다.")
    hub = os.environ.get("HUB_URL", "https://ai-ceo-hub.onrender.com").rstrip("/")
    token = os.environ.get("SHORTS_HOOK_TOKEN", "").strip()
    if not token:
        print(json.dumps(items[:5], ensure_ascii=False, indent=1))
        sys.exit("SHORTS_HOOK_TOKEN이 없어 CEO Hub로 보내지 못했습니다.")
    body = json.dumps({"batch": os.environ.get("BATCH", ""), "items": items}).encode()
    req = urllib.request.Request(f"{hub}/api/shorts/hook/candidates", data=body, method="POST", headers={"Content-Type": "application/json", "x-shorts-token": token, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        print("HUB_RESULT " + r.read().decode()[:300])


if __name__ == "__main__":
    main()
