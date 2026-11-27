"""CEO Hub에서 가져온 대본으로 세로 쇼츠를 만들고 구국열사 채널에 비공개 업로드한 뒤 결과를 보고.

장면마다: AI 음성(edge-tts, 실패 시 gTTS) → Pixabay 배경 영상(가운데 잘라 9:16) → 큰 자막 → 장면 영상
장면을 이어 붙여 업로드. 비밀값은 환경변수로만 받고 출력하지 않음.
"""
import json
import os
import random
import re
import subprocess
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from youtube_upload import upload  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) CEO-Shorts/1.0 (+https://alpinu83.github.io/shorts-factory/)"
HUB = os.environ.get("HUB_URL", "https://ai-ceo-hub.onrender.com").rstrip("/")
VOICE = os.environ.get("TTS_VOICE", "ko-KR-InJoonNeural")
FONT = "Noto Sans CJK KR"
W, H = 1080, 1920


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} 실패: {p.stderr[-400:]}")
    return p.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())


def tts(text, out, rate):
    try:
        run(["edge-tts", "--voice", VOICE, f"--rate={rate}", "--text", text, "--write-media", out])
        if os.path.getsize(out) > 1000:
            return "edge-tts"
    except Exception as e:  # noqa: BLE001
        print(f"edge-tts 실패 → gTTS로 대체: {str(e)[:120]}")
    from gtts import gTTS
    gTTS(text=text, lang="ko").save(out)
    return "gtts"


_bg_cache = {}
_used = set()
_credits = []


def pixabay_video(keywords, min_dur):
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        return None
    for q in [keywords, keywords.split(",")[0], "city", "crowd"]:
        q = q.strip()
        if not q:
            continue
        if q not in _bg_cache:
            url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode({"key": key, "q": q, "per_page": 20, "safesearch": "true"})
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    _bg_cache[q] = json.load(r).get("hits", [])
            except Exception as e:  # noqa: BLE001
                print(f"pixabay 검색 실패({q}): {type(e).__name__}")
                _bg_cache[q] = []
        hits = [h for h in _bg_cache[q] if h["id"] not in _used]
        hits.sort(key=lambda h: (h.get("duration", 0) < min_dur, -h.get("views", 0)))
        if hits:
            h = random.choice(hits[:4])
            _used.add(h["id"])
            v = h["videos"].get("medium") or h["videos"].get("small") or h["videos"].get("large")
            path = f"bg_{h['id']}.mp4"
            req = urllib.request.Request(v["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
                f.write(r.read())
            _credits.append(h.get("user") or "Pixabay")
            return path
    return None


def wrap(text, width=13):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = f"{cur} {w}".strip()
        else:
            if cur:
                lines.append(cur)
            while len(w) > width:
                lines.append(w[:width])
                w = w[width:]
            cur = w
    if cur:
        lines.append(cur)
    return lines


def ass_time(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ass_escape(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")")


def write_ass(path, title, text, dur):
    lines = wrap(text)
    chunks = [lines[i:i + 2] for i in range(0, len(lines), 2)] or [[text]]
    total_chars = sum(len("".join(c)) for c in chunks) or 1
    t, events = 0.0, []
    newline = "\\N"
    for c in chunks:
        d = dur * len("".join(c)) / total_chars
        body = newline.join(ass_escape(x) for x in c)
        events.append(f"Dialogue: 0,{ass_time(t)},{ass_time(min(dur, t + d))},Sub,,0,0,0,,{body}")
        t += d
    title_lines = newline.join(ass_escape(x) for x in wrap(title, 15)[:2])
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{FONT},88,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,2,60,60,560,1
Style: Title,{FONT},62,&H00FFFFFF,&H00FFFFFF,&H00000000,&HD0102080,-1,0,0,0,100,100,0,0,3,18,0,8,70,70,170,1
Style: Brand,{FONT},44,&H0000D7FF,&H0000D7FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,8,60,60,90,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,{ass_time(0)},{ass_time(dur)},Brand,,0,0,0,,구국열사
Dialogue: 0,{ass_time(0)},{ass_time(dur)},Title,,0,0,0,,{title_lines}
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")


def make_scene(i, scene, title, rate):
    audio = f"s{i}.mp3"
    engine = tts(scene["text"], audio, rate)
    dur = duration(audio) + 0.35
    ass = f"s{i}.ass"
    write_ass(ass, title, scene["text"], dur)
    bg = pixabay_video(scene.get("keywords") or "city", dur)
    out = f"scene{i}.mp4"
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=30,eq=brightness=-0.12:saturation=0.85,subtitles={ass}"
    if bg:
        inputs = ["-stream_loop", "-1", "-i", bg]
    else:
        inputs = ["-f", "lavfi", "-i", f"color=c=0x1a1a2e:s={W}x{H}:r=30"]
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-i", audio, "-filter_complex", f"[0:v]{vf}[v];[1:a]apad=pad_dur=0.35[a]", "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", out])
    return out, dur, engine


def render(job):
    script = job["script"]
    title = script["title"]
    for rate in ["+12%", "+28%"]:
        _used.clear()
        _credits.clear()
        parts, total, engines = [], 0.0, set()
        for i, sc in enumerate(script["scenes"]):
            p, d, eng = make_scene(i, sc, title, rate)
            parts.append(p)
            total += d
            engines.add(eng)
        if total <= 58.5:
            break
        print(f"길이 {total:.1f}초 → 더 빠르게 다시 낭독")
    with open("list.txt", "w") as f:
        f.write("\n".join(f"file '{p}'" for p in parts))
    final = f"short_{job['id']}.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "-t", "59", final])
    return final, min(total, 59.0), engines


def describe(job):
    s = job["script"]
    src = "\n".join(f"- {u}" for u in s.get("sources", [])) or "- (출처 없음)"
    credits = ", ".join(dict.fromkeys(_credits)) or "Pixabay"
    tags = " ".join(["#Shorts", *[h if h.startswith("#") else f"#{h}" for h in s.get("hashtags", [])]])
    return f"""{s['title']}

[출처]
{src}

[배경 영상] Pixabay (https://pixabay.com) — {credits}
[안내] 이 영상은 AI 음성으로 제작되었습니다. 해설은 채널의 의견입니다.

{tags}"""


def report(job_id, body):
    token = os.environ.get("SHORTS_HOOK_TOKEN", "").strip()
    req = urllib.request.Request(f"{HUB}/api/shorts/hook/jobs/{job_id}/result", data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", "x-shorts-token": token, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print("HUB_RESULT " + r.read().decode()[:200])
    except Exception as e:  # noqa: BLE001
        print(f"HUB 보고 실패: {type(e).__name__}")


def main():
    jobs = json.load(open(sys.argv[1], encoding="utf-8"))
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', '')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    failed = 0
    for job in jobs:
        try:
            final, dur, engines = render(job)
            s = job["script"]
            res = upload(final, f"{s['title']} #Shorts"[:100], describe(job), privacy="private", tags=[h.lstrip("#") for h in s.get("hashtags", [])][:10])
            report(job["id"], {"ok": True, "videoId": res["videoId"], "url": res["url"], "channelTitle": res.get("channelTitle"), "privacy": res.get("privacy"), "durationSec": round(dur, 1), "runUrl": run_url, "tts": sorted(engines)})
        except SystemExit as e:
            failed += 1
            report(job["id"], {"ok": False, "error": str(e)[:300], "runUrl": run_url})
        except Exception as e:  # noqa: BLE001
            failed += 1
            report(job["id"], {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "runUrl": run_url})
    if failed:
        sys.exit(f"{failed}건 실패")


if __name__ == "__main__":
    main()
