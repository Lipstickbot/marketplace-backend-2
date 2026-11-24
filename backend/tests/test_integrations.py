from datetime import UTC, datetime
import hashlib
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.test_auth import A, D, auth
from backend.tests.test_execution import RuntimeFake, EngineFake, SECRET, file_row
from backend.tests.test_marketplace import NOW


class IntegrationFake(RuntimeFake):
    def __init__(self):
        super().__init__()
        self.keys = []

    def __call__(self, request):
        if request.url.path == '/rest/v1/agent_integrations':
            self.requests.append(request)
            assert request.headers['apikey'] == 'sb_secret_test'
            if request.method == 'POST':
                row = dict(id=str(uuid4()), revoked_at=None, created_at=NOW, **json.loads(request.content))
                self.keys.append(row)
                return httpx.Response(201,json=[row])
            rows = list(self.keys)
            for key,value in request.url.params.items():
                if value.startswith('eq.'):
                    rows = [row for row in rows if str(row.get(key)) == value[3:]]
                if value == 'is.null':
                    rows = [row for row in rows if row.get(key) is None]
                if value.startswith('gt.'):
                    rows = [row for row in rows if datetime.fromisoformat(row[key]) > datetime.fromisoformat(value[3:])]
            if request.method == 'PATCH':
                for row in rows: row.update(json.loads(request.content))
            # Simulate PostgREST's select to ensure list endpoint doesn't fetch hashes.
            fields = request.url.params.get('select','*')
            return httpx.Response(200,json=rows if fields == '*' else [{k:v for k,v in r.items() if k in fields.split(',')} for r in rows])
        if request.headers.get('apikey') == 'sb_secret_test' and request.method == 'GET' and request.url.path.startswith('/rest/v1/'):
            # Service-only integration reads must explicitly scope private data.
            if request.url.path == '/rest/v1/connect_requests':
                assert request.url.params['company_id'] == 'eq.'+A
            if request.url.path == '/rest/v1/agent_files':
                assert request.url.params['company_id'] == 'eq.'+A
                assert request.url.params['user_id'] == 'eq.'+A
            headers = dict(request.headers); headers.update(apikey='sb_publishable_test',authorization='Bearer a')
            return super().__call__(httpx.Request(request.method,request.url,headers=headers))
        return super().__call__(request)


@pytest.fixture
def environment():
    remote, engine = IntegrationFake(), EngineFake()
    settings=Settings(supabase_url='https://project.supabase.co',supabase_publishable_key='sb_publishable_test',
        supabase_secret_key='sb_secret_test',engine_jwt_secret=SECRET,auth_requests_per_minute=1000)
    with TestClient(create_app(settings,transport=httpx.MockTransport(remote),engine_transport=httpx.MockTransport(engine))) as client:
        yield client,remote,engine


def create(client, **changes):
    response=client.post('/api/integrations',headers=auth(),json={'agent_slug':'marketing','name':'Shop assistant','task':'Answer for my shop',**changes})
    assert response.status_code == 201,response.text
    return response.json()


def ask(client,key,**changes):
    return client.post('/api/v1/chat/completions',headers={'Authorization':'Bearer '+key},json={
        'model':'keme/marketing','messages':[{'role':'user','content':'Plan a campaign'}],**changes})


def test_keys_hash_only_scoped_and_not_exposed_again(environment):
    client,remote,_=environment
    data=create(client); key=data['api_key']
    assert key.startswith('keme_') and len(key)==48
    assert remote.keys[0]['key_hash']==hashlib.sha256(key.encode()).hexdigest()
    assert key not in json.dumps(remote.keys) and 'key_hash' not in json.dumps(data)
    listed=client.get('/api/integrations',headers=auth())
    assert listed.status_code==200 and len(listed.json())==1
    assert key not in listed.text and 'key_hash' not in listed.text
    assert remote.keys[0]['user_id']==A and remote.keys[0]['company_id']==A


def test_openai_text_bridge_uses_task_engine_and_audit(environment):
    client,remote,engine=environment
    key=create(client)['api_key']; response=ask(client,key)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['object']=='chat.completion' and result['choices'][0]['message']['role']=='assistant'
    assert result['usage']=={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}
    assert result['keme']['mode']=='mock' and result['keme']['audit_saved'] is True
    call=[r for r in engine.requests if r.url.path.endswith('/run')][-1]
    assert 'Answer for my shop' in json.loads(call.content)['message']
    assert len(remote.records['agent_runs'])==1
    assert 'Answer for my shop' not in json.dumps(remote.records['agent_runs'])
    model=client.get('/api/v1/models',headers={'Authorization':'Bearer '+key})
    assert [r['id'] for r in model.json()['data']]==['keme/marketing']


def test_revoked_expired_wrong_keys_and_other_agents_cannot_run(environment):
    client,remote,engine=environment
    data=create(client); key=data['api_key']
    assert ask(client,key,model='keme/hr').status_code==403
    assert ask(client,'keme_'+'x'*43).status_code==401
    assert client.get('/api/v1/models',headers=auth()).status_code==401
    remote.keys[0]['expires_at']='2020-01-01T00:00:00+00:00'
    assert ask(client,key).status_code==401
    remote.keys[0]['expires_at']='2099-01-01T00:00:00+00:00'
    assert client.delete('/api/integrations/'+data['integration']['id'],headers=auth()).status_code==204
    assert ask(client,key).status_code==401
    assert not engine.requests


def test_approval_role_and_ownership_rechecked(environment):
    client,remote,engine=environment
    key=create(client)['api_key']
    remote.records['connect_requests'][0]['status']='rejected'
    assert ask(client,key).status_code==403
    assert client.post('/api/integrations',headers=auth(),json={'agent_slug':'marketing','name':'No approval'}).status_code==403
    remote.profiles['a']['role']='developer'
    assert ask(client,key).status_code==403
    assert client.get('/api/integrations',headers=auth('dev')).status_code==403
    assert client.delete('/api/integrations/'+str(uuid4()),headers=auth()).status_code==403
    assert not engine.requests


def test_foreign_documents_and_credentials_rejected_and_stream_explicit(environment):
    client,remote,_=environment
    foreign=file_row(user_id=D,company_id=D);remote.records['agent_files'].append(foreign)
    result=client.post('/api/integrations',headers=auth(),json={'agent_slug':'marketing','name':'Wrong file','file_ids':[foreign['id']]})
    assert result.status_code==404
    key=create(client)['api_key']
    assert ask(client,key,stream=True).status_code==422
    assert ask(client,key,messages=[{'role':'user','content':[{'type':'text','text':'no'}]}]).status_code==422
    assert ask(client,key,messages=[{'role':'assistant','content':'wrong last role'}]).status_code==422
    remote.keys[0]['user_id']=D
    assert client.delete('/api/integrations/'+remote.keys[0]['id'],headers=auth()).status_code==404


def test_configured_documents_used_without_allowing_caller_to_change_scope(environment):
    client,remote,engine=environment
    row=file_row();remote.records['agent_files'].append(row);remote.blobs[row['object_path']]=b'brief'
    key=create(client,file_ids=[row['id']],language='kk')['api_key']
    result=ask(client,key)
    assert result.status_code==200,result.text
    call=[r for r in engine.requests if r.url.path.endswith('/run')][-1]
    payload=json.loads(call.content)
    assert payload['language']=='kk' and len(payload['file_ids'])==1
    assert ask(client,key,file_ids=[str(uuid4())]).status_code==422


def test_engine_failure_is_not_retried_and_preserves_error(environment):
    client,remote,engine=environment
    key=create(client)['api_key'];engine.run_response=httpx.Response(429,json={'error':{'code':'rate_limited'}})
    response=ask(client,key)
    assert response.status_code==429
    assert len([r for r in engine.requests if r.url.path.endswith('/run')])==1
