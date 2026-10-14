import asyncio
import re
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

import httpx
import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path

ROOT = Path(__file__).parent
app = FastAPI(title="twitterno", docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
POST = re.compile(r'https://(?:www\.)?(?:x\.com|twitter\.com)/[A-Za-z0-9_]+/status/([0-9]+)(?:[/?#].*)?\Z')
MAX_BYTES = 256 * 1024 * 1024
cache = {}
requests = defaultdict(deque)
slots = asyncio.Semaphore(3)

class Analyze(BaseModel):
    url: str

def canonical_url(value):
    if len(value) > 2048:
        raise HTTPException(400, '投稿URLが長すぎます。')
    match = POST.fullmatch(value.strip())
    if not match:
        raise HTTPException(400, 'Xの投稿URL（https://x.com/ユーザー名/status/数字）を入力してください。')
    return f'https://x.com/i/status/{match.group(1)}'

def media_url(value):
    try:
        p = urlparse(value or '')
        return p.scheme == 'https' and p.hostname == 'video.twimg.com' and p.port in (None, 443) and not p.username and not p.password
    except ValueError:
        return False

def extract(url):
    with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True,
                          'socket_timeout': 15, 'retries': 1, 'extractor_retries': 1,
                          'noplaylist': False}) as dl:
        return dl.extract_info(url, download=False)

@app.middleware('http')
async def headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response

@app.get('/')
async def index():
    return FileResponse(ROOT / 'static/index.html')

@app.get('/health')
async def health():
    return {'status': 'ok'}

@app.post('/api/analyze')
async def analyze(body: Analyze, request: Request):
    url = canonical_url(body.url)
    now = time.monotonic()
    for key in list(cache):
        if cache[key]['expires'] < now:
            del cache[key]
    for key in list(requests):
        if not requests[key] or requests[key][-1] < now - 60:
            del requests[key]
    ip = request.client.host if request.client else 'unknown'
    history = requests[ip]
    while history and history[0] < now - 60:
        history.popleft()
    if len(history) >= 6 or len(cache) >= 500 or len(requests) > 10000:
        raise HTTPException(429, 'アクセスが集中しています。少し待ってお試しください。')
    history.append(now)
    if slots.locked():
        raise HTTPException(503, '処理が混み合っています。少し待ってお試しください。')
    try:
        async with slots:
            info = await asyncio.to_thread(extract, url)
    except Exception:
        raise HTTPException(422, '動画を取得できませんでした。公開投稿か、動画付きの投稿か確認してください。X側の制限で取得できない場合もあります。')
    entries = info.get('entries') or [info]
    videos = []
    for n, entry in enumerate(entries):
        if not entry:
            continue
        choices = []
        seen = set()
        for f in sorted(entry.get('formats', []), key=lambda f: f.get('height') or 0, reverse=True):
            if f.get('ext') != 'mp4' or f.get('protocol') != 'https' or not media_url(f.get('url')):
                continue
            height = f.get('height') or 0
            if height in seen:
                continue
            seen.add(height)
            token = secrets.token_urlsafe(24)
            filename = f'x-{url.rsplit("/", 1)[-1]}-{n+1}-{height or "original"}.mp4'
            cache[token] = {'url': f['url'], 'filename': filename, 'expires': time.monotonic() + 600}
            choices.append({'label': f'{height}p' if height else 'オリジナル', 'download': f'/api/download/{token}'})
        if choices:
            videos.append({'title': f'動画 {n+1}', 'qualities': choices})
    if not videos:
        raise HTTPException(422, 'ダウンロードできるMP4動画が見つかりませんでした。')
    return {'videos': videos}

@app.get('/api/download/{token}')
async def download(token: str):
    item = cache.get(token)
    if not item or item['expires'] < time.monotonic():
        cache.pop(token, None)
        raise HTTPException(410, 'リンクの有効期限が切れました。投稿URLを再度解析してください。')
    client = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=False)
    response = None
    try:
        response = await client.send(client.build_request('GET', item['url']), stream=True)
        length = response.headers.get('content-length')
        if response.status_code != 200 or (length and int(length) > MAX_BYTES):
            raise ValueError('unavailable')
    except Exception:
        if response is not None:
            await response.aclose()
        await client.aclose()
        raise HTTPException(502, '動画を取得できませんでした。時間をおいて再度お試しください。')
    async def stream():
        total = 0
        try:
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise RuntimeError('Video exceeds size limit')
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()
    headers = {'Content-Disposition': f'attachment; filename="{item["filename"]}"', 'Cache-Control': 'no-store'}
    if length:
        headers['Content-Length'] = length
    return StreamingResponse(stream(), media_type='video/mp4', headers=headers)
