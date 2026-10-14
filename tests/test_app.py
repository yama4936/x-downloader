import time
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import app as service

@pytest.fixture(autouse=True)
def clear():
    service.cache.clear()
    service.requests.clear()

@pytest.fixture
def client():
    return TestClient(service.app)

@pytest.mark.parametrize('url', ['http://x.com/a/status/1', 'https://x.com.evil.test/a/status/1', 'https://localhost/a/status/1', 'https://x.com/a/status/nope', 'https://x.com@evil.test/a/status/1'])
def test_reject_invalid_posts(url):
    with pytest.raises(HTTPException):
        service.canonical_url(url)

def test_canonical():
    assert service.canonical_url('https://twitter.com/a/status/123?s=20') == 'https://x.com/i/status/123'

@pytest.mark.parametrize('url', ['http://video.twimg.com/a.mp4', 'https://video.twimg.com.evil.test/a.mp4', 'https://user@video.twimg.com/a.mp4', 'https://video.twimg.com:444/a.mp4'])
def test_reject_media(url):
    assert not service.media_url(url)

def test_home(client):
    r = client.get('/')
    assert r.status_code == 200
    assert 'twitterno' in r.text
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']

def test_analyze_and_download(client, monkeypatch):
    monkeypatch.setattr(service, 'extract', lambda _: {'formats': [
        {'ext':'mp4','protocol':'https','height':720,'url':'https://video.twimg.com/test.mp4'},
        {'ext':'mp4','protocol':'https','height':1080,'url':'https://evil.test/test.mp4'}]})
    result = client.post('/api/analyze', json={'url':'https://x.com/a/status/123'})
    assert result.status_code == 200
    quality = result.json()['videos'][0]['qualities']
    assert len(quality) == 1
    assert quality[0]['label'] == '720p'
    original = httpx.AsyncClient
    monkeypatch.setattr(service.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'video')), **kw))
    r = client.get(quality[0]['download'])
    assert r.content == b'video'
    assert 'attachment' in r.headers['content-disposition']

def test_expired(client):
    service.cache['old'] = {'expires':time.monotonic()-1}
    assert client.get('/api/download/old').status_code == 410

def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(service, 'extract', lambda _: {'formats':[]})
    for _ in range(6):
        assert client.post('/api/analyze', json={'url':'https://x.com/a/status/123'}).status_code == 422
    assert client.post('/api/analyze', json={'url':'https://x.com/a/status/123'}).status_code == 429

def test_extractor_failure(client, monkeypatch):
    def fail(_):
        raise RuntimeError('private failure')
    monkeypatch.setattr(service, 'extract', fail)
    r = client.post('/api/analyze', json={'url':'https://x.com/a/status/123'})
    assert r.status_code == 422
    assert 'private failure' not in r.text

def test_download_redirect_rejected(client, monkeypatch):
    service.cache['token'] = {'url':'https://video.twimg.com/test.mp4','expires':time.monotonic()+600,'filename':'test.mp4'}
    original = httpx.AsyncClient
    monkeypatch.setattr(service.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={'location':'https://localhost/private'})), **kw))
    assert client.get('/api/download/token').status_code == 502
