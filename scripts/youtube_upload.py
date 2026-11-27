"""YouTube 업로드 (표준 라이브러리만 사용). 비밀값은 환경변수로만 받고 절대 출력하지 않음."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def access_token():
    data = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"].strip(),
        "client_secret": os.environ["YT_CLIENT_SECRET"].strip(),
        "refresh_token": os.environ["YT_REFRESH_TOKEN"].strip(),
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["access_token"]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        err = json.loads(body).get("error", "unknown") if body.startswith("{") else "unknown"
        sys.exit(f"TOKEN_ERROR: {e.code} {err} (리프레시 토큰·클라이언트 ID·보안 비밀 확인 필요)")


def upload(path, title, description="", privacy="private", tags=None):
    token = access_token()
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": tags or [], "categoryId": "25"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
    }
    size = os.path.getsize(path)
    init = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(meta).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(size),
        },
    )
    try:
        with urllib.request.urlopen(init, timeout=60) as r:
            location = r.headers["Location"]
    except urllib.error.HTTPError as e:
        sys.exit(f"UPLOAD_INIT_ERROR: {e.code} {e.read().decode(errors='replace')[:600]}")
    with open(path, "rb") as f:
        put = urllib.request.Request(location, data=f.read(), method="PUT", headers={"Content-Type": "video/mp4"})
    try:
        with urllib.request.urlopen(put, timeout=600) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"UPLOAD_ERROR: {e.code} {e.read().decode(errors='replace')[:600]}")
    out = {
        "videoId": res.get("id"),
        "url": f"https://youtube.com/shorts/{res.get('id')}",
        "channelId": res.get("snippet", {}).get("channelId"),
        "channelTitle": res.get("snippet", {}).get("channelTitle"),
        "privacy": res.get("status", {}).get("privacyStatus"),
        "uploadStatus": res.get("status", {}).get("uploadStatus"),
    }
    print("UPLOAD_RESULT " + json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    upload(sys.argv[1], os.environ.get("VIDEO_TITLE") or "[테스트] 업로드 연결 확인", "CEO Shorts 업로드 연결 테스트 영상입니다.")
