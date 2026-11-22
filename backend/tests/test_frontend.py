from fastapi.testclient import TestClient
import httpx

from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.test_execution import RuntimeFake, EngineFake, SECRET


def test_browser_api_prefix_preserves_auth_and_upload_limits():
    remote = RuntimeFake()
    settings = Settings(supabase_url="https://project.supabase.co", supabase_publishable_key="sb_publishable_test",
                        supabase_secret_key="sb_secret_test", engine_jwt_secret=SECRET)
    app = create_app(settings, transport=httpx.MockTransport(remote), engine_transport=httpx.MockTransport(EngineFake()))
    with TestClient(app) as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/agents').json() == client.get('/agents').json()
        assert client.get('/api/auth/me').status_code == 401
        login = client.post('/api/auth/login', json={'email': 'user@example.com', 'password': 'Example-password-2026'})
        assert login.status_code == 200
        headers = {'Authorization': 'Bearer ' + login.json()['session']['access_token']}
        assert client.get('/api/auth/me', headers=headers).json()['role'] == 'business'
        # A valid multipart body above the JSON limit still reaches the upload route.
        response = client.post('/api/files/upload', headers=headers, data={'purpose': 'brief'},
                               files={'file': ('brief.txt', b'x' * (600 * 1024), 'text/plain')})
        assert response.status_code == 201
        assert client.post('/api/agents/marketing/run', headers=headers, content=b'x' * (513 * 1024)).status_code == 413


def test_browser_auth_prefix_keeps_rate_limiter():
    remote = RuntimeFake()
    settings = Settings(supabase_url="https://project.supabase.co", supabase_publishable_key="sb_publishable_test",
                        auth_requests_per_minute=1)
    with TestClient(create_app(settings, transport=httpx.MockTransport(remote))) as client:
        body = {'email': 'user@example.com', 'password': 'Example-password-2026'}
        assert client.post('/api/auth/login', json=body).status_code == 200
        assert client.post('/auth/login', json=body).status_code == 429
