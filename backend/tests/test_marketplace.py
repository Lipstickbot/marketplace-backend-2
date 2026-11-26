import json
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.test_auth import A, D, M, FakeSupabase, auth

AGENT = "10000000-0000-4000-8000-000000000001"
REQUEST = "20000000-0000-4000-8000-000000000001"
SUBMISSION = "30000000-0000-4000-8000-000000000001"
NOW = "2026-11-21T03:00:00Z"


def card(**changes):
    return {"id":AGENT,"slug":"marketing","name":"Marketing","description":"Demo","category":"marketing",
            "status":"published","developer_id":None,"engine_slug":"marketing","version":"1.0.0",
            "supported_languages":["ru","kk","en"],"capabilities":[],"accepted_file_purposes":[],
            "input_schema":{},"output_schema":{},"created_at":NOW,"updated_at":NOW,**changes}


def connection(**changes):
    return {"id":REQUEST,"company_id":A,"requested_by":A,"agent_id":AGENT,"message":"","status":"pending",
            "reviewed_by":None,"reviewed_at":None,"review_note":None,"created_at":NOW,"updated_at":NOW,**changes}


def submission(**changes):
    return {"id":SUBMISSION,"developer_id":D,"name":"Agent","description":"Description","category":"support",
            "repository_url":None,"status":"pending","published_agent_id":None,"reviewed_by":None,
            "reviewed_at":None,"review_note":None,"created_at":NOW,"updated_at":NOW,**changes}


class MarketplaceFake(FakeSupabase):
    def __init__(self):
        super().__init__()
        self.records={"agents":[card()],"connect_requests":[connection()],"agent_submissions":[submission()]}

    def __call__(self, request):
        table=request.url.path.removeprefix('/rest/v1/')
        if table not in self.records and not table.startswith('rpc/'):
            return super().__call__(request)
        if table=='rpc/is_current_session_active':
            return super().__call__(request)
        self.requests.append(request)
        assert request.headers['apikey']=='sb_publishable_test'
        override=self.overrides.get((request.method,request.url.path))
        if override is not None:
            return override(request) if callable(override) else override
        if table.startswith('rpc/'):
            assert request.headers['authorization']=='Bearer admin'
            payload=json.loads(request.content)
            if table=='rpc/create_catalog_agent':
                return httpx.Response(200,json=card(**payload['p_data']))
            if table=='rpc/update_catalog_agent':
                return httpx.Response(200,json=card(**payload['p_changes']))
            if table=='rpc/review_connect_request':
                return httpx.Response(200,json=connection(status=payload['p_decision'],reviewed_by=M,reviewed_at=NOW))
            if table=='rpc/review_agent_submission':
                return httpx.Response(200,json=submission(status=payload['p_decision'],reviewed_by=M,reviewed_at=NOW,published_agent_id=AGENT))
            raise AssertionError('Unknown RPC')
        if request.method=='POST':
            assert request.headers['Prefer']=='return=representation'
            payload=json.loads(request.content)
            result=connection(**payload) if table=='connect_requests' else submission(**payload)
            return httpx.Response(201,json=[result])
        assert request.method=='GET'
        rows=list(self.records[table])
        for key,value in request.url.params.items():
            if value.startswith('eq.'):
                expected=json.loads(value[3:]) if value[3:].startswith('"') else value[3:]
                rows=[row for row in rows if str(row.get(key))==expected]
            elif value.startswith('in.('):
                rows=[row for row in rows if row.get(key) in value[4:-1].split(',')]
        offset=int(request.url.params.get('offset',0))
        limit=int(request.url.params.get('limit',100))
        return httpx.Response(200,json=rows[offset:offset+limit])


@pytest.fixture
def environment():
    remote=MarketplaceFake()
    app=create_app(Settings(supabase_url='https://project.supabase.co',supabase_publishable_key='sb_publishable_test'),
                   transport=httpx.MockTransport(remote))
    with TestClient(app) as client:
        yield client,remote


def test_public_catalog_is_anonymous_even_with_admin_header_and_hides_drafts(environment):
    client,remote=environment
    remote.records['agents'].append(card(id=str(uuid4()),slug='private',status='draft'))
    response=client.get('/agents',headers=auth('admin'))
    assert response.status_code==200 and len(response.json()['items'])==1
    assert all('authorization' not in request.headers for request in remote.requests)
    assert client.get('/agents/private').status_code==404
    assert client.get('/agents/marketing').json()['engine_slug']=='marketing'


def test_catalog_pagination_filters_and_literal_search(environment):
    client,remote=environment
    remote.records['agents'].append(card(id=str(uuid4()),slug='second'))
    response=client.get('/agents',params={'limit':1,'offset':0,'q':'100%_*,x','category':'marketing','status':'published'})
    assert response.json()['has_more'] is True
    request=remote.requests[-1]
    assert request.url.params['limit']=='2'
    assert request.url.params['order']=='created_at.desc,id.desc'
    assert request.url.params['name']==r'imatch."100%_\\*,x"'
    assert request.url.params['category']=='eq."marketing"'
    assert client.get('/agents',params={'limit':1,'offset':2}).json()['items']==[]


@pytest.mark.parametrize('params',[{'limit':0},{'limit':101},{'offset':-1},{'offset':10001},{'status':'draft'},{'q':''}])
def test_invalid_public_queries_are_rejected(environment,params):
    client,_=environment
    assert client.get('/agents',params=params).status_code==422


def test_business_creates_request_with_server_owned_identity(environment):
    client,remote=environment
    response=client.post('/connect-requests',headers=auth(),json={'agent_id':AGENT,'message':'Connect us'})
    assert response.status_code==201
    request=remote.requests[-1]
    assert json.loads(request.content)=={'agent_id':AGENT,'company_id':A,'requested_by':A,'message':'Connect us'}
    assert request.headers['authorization']=='Bearer a'
    assert response.json()['status']=='pending'
    remote.records['agents'][0]['status']='coming_soon'
    assert client.post('/connect-requests',headers=auth(),json={'agent_id':AGENT}).status_code==404


def test_business_reads_only_own_requests_and_foreign_detail_is_404(environment):
    client,remote=environment
    foreign=str(uuid4())
    remote.records['connect_requests'].append(connection(id=foreign,company_id=M,requested_by=M))
    assert len(client.get('/connect-requests',headers=auth()).json()['items'])==1
    assert remote.requests[-1].url.params['company_id']==f'eq.{A}'
    assert client.get(f'/connect-requests/{foreign}',headers=auth()).status_code==404
    assert client.get(f'/connect-requests/{REQUEST}',headers=auth()).status_code==200
    assert client.get('/connect-requests',headers=auth('dev')).status_code==403


@pytest.mark.parametrize('payload',[{'company_id':M},{'requested_by':M},{'status':'approved'},{'reviewed_by':M}])
def test_business_cannot_inject_owner_or_moderation_fields(environment,payload):
    client,_=environment
    assert client.post('/connect-requests',headers=auth(),json={'agent_id':AGENT,**payload}).status_code==422


def test_developer_submission_and_owned_cards(environment):
    client,remote=environment
    response=client.post('/agent-submissions',headers=auth('dev'),json={
        'name':' Agent ','description':'Description','category':'support','repository_url':'https://github.com/example/agent'})
    assert response.status_code==201
    assert json.loads(remote.requests[-1].content)['developer_id']==D
    assert client.get('/agent-submissions',headers=auth('dev')).json()['items'][0]['id']==SUBMISSION
    foreign=str(uuid4())
    remote.records['agent_submissions'].append(submission(id=foreign,developer_id=M))
    assert client.get(f'/agent-submissions/{foreign}',headers=auth('dev')).status_code==404
    assert client.get(f'/agent-submissions/{SUBMISSION}',headers=auth('dev')).status_code==200
    remote.records['agents'][0]['developer_id']=D
    assert len(client.get('/developer/agents',headers=auth('dev')).json()['items'])==1
    assert remote.requests[-1].url.params['developer_id']==f'eq.{D}'
    business=client.post('/agent-submissions',headers=auth(),json={'name':'Agent','description':'Description','category':'support'})
    assert business.status_code==201
    assert business.json()['developer_id']==A and business.json()['status']=='pending'
    remote.records['agent_submissions'].append(submission(id=str(uuid4()),developer_id=A))
    assert len(client.get('/agent-submissions',headers=auth()).json()['items'])==1
    assert client.get(f'/agent-submissions/{SUBMISSION}',headers=auth()).status_code==404
    assert client.post('/agent-submissions',headers=auth('admin'),json={'name':'Agent','description':'Description','category':'support'}).status_code==403


@pytest.mark.parametrize('extra',[{'developer_id':M},{'status':'approved'},{'repository_url':'http://example.com/agent'},
                                  {'repository_url':'https://user:password@example.com/agent'},{'name':'   '}])
def test_submission_rejects_identity_privilege_and_invalid_fields(environment,extra):
    client,_=environment
    assert client.post('/agent-submissions',headers=auth('dev'),json={'name':'Agent','description':'Description','category':'support',**extra}).status_code==422


def test_admin_catalog_create_and_patch_use_authenticated_atomic_rpc(environment):
    client,remote=environment
    assert client.post('/admin/agents',headers=auth('admin'),json={'slug':'new','name':'New','category':'support'}).status_code==201
    assert json.loads(remote.requests[-1].content)['p_data']['status']=='draft'
    response=client.patch(f'/admin/agents/{AGENT}',headers=auth('admin'),json={'name':'Renamed'})
    assert response.json()['name']=='Renamed'
    assert json.loads(remote.requests[-1].content)=={'p_agent_id':AGENT,'p_changes':{'name':'Renamed'}}
    assert client.get('/admin/agents',headers=auth('admin')).status_code==200
    for patch in [{},{'name':None},{'id':M},{'role':'admin'}]:
        assert client.patch(f'/admin/agents/{AGENT}',headers=auth('admin'),json=patch).status_code==422
    assert client.post('/admin/agents',headers=auth('admin'),json={'slug':'no-engine','name':'Bad','category':'support','status':'published'}).status_code==422


def test_admin_reviews_pass_only_decision_and_current_jwt(environment):
    client,remote=environment
    response=client.post(f'/admin/connect-requests/{REQUEST}/review',headers=auth('admin'),json={'decision':'approved','review_note':'OK'})
    assert response.status_code==200 and response.json()['reviewed_by']==M
    assert json.loads(remote.requests[-1].content)=={'p_request_id':REQUEST,'p_decision':'approved','p_review_note':'OK'}
    response=client.post(f'/admin/agent-submissions/{SUBMISSION}/review',headers=auth('admin'),
                         json={'decision':'approved','publication_slug':'external-agent'})
    assert response.status_code==200
    assert json.loads(remote.requests[-1].content)['p_publication_slug']=='external-agent'
    assert client.get('/admin/connect-requests',headers=auth('admin')).status_code==200
    assert client.get('/admin/agent-submissions',headers=auth('admin')).status_code==200


@pytest.mark.parametrize("engine_status", [200, 404, 503])
def test_activation_checks_engine_before_server_only_review(engine_status):
    remote = MarketplaceFake()
    writes = []
    def platform(request):
        if request.url.path == "/rest/v1/rpc/activate_agent_submission":
            assert request.headers["apikey"] == "sb_secret_test"
            assert "authorization" not in request.headers
            writes.append(json.loads(request.content))
            return httpx.Response(200, json=submission(status="approved", reviewed_by=M,
                reviewed_at=NOW, published_agent_id=AGENT))
        return remote(request)
    def engine(request):
        assert request.method == "GET" and request.url.path == "/agents/sales-assistant"
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(engine_status, json={
            "slug": "sales-assistant", "version": "1.0", "supported_languages": ["ru"],
            "capabilities": ["sales"], "accepted_file_purposes": ["brief"],
            "input_schema": {}, "output_schema": {},
        } if engine_status == 200 else {"error": {"code": "agent_not_found" if engine_status == 404 else "unavailable"}})
    settings = Settings(supabase_url="https://project.supabase.co", supabase_publishable_key="sb_publishable_test",
        supabase_secret_key="sb_secret_test", engine_jwt_secret="test-signing-secret-at-least-32-chars")
    with TestClient(create_app(settings, transport=httpx.MockTransport(platform),
                              engine_transport=httpx.MockTransport(engine))) as client:
        response = client.post(f"/admin/agent-submissions/{SUBMISSION}/review", headers=auth("admin"),
            json={"decision": "approved", "engine_slug": "sales-assistant"})
    assert response.status_code == {200: 200, 404: 422, 503: 503}[engine_status]
    if engine_status == 200:
        assert writes[0]["p_actor"] == M
        assert writes[0]["p_card"]["slug"] == writes[0]["p_card"]["engine_slug"] == "sales-assistant"
        assert writes[0]["p_card"]["accepted_file_purposes"] == ["brief"]
    else:
        assert not writes


@pytest.mark.parametrize('body',[{'decision':'pending'},{'decision':'approved'},{'decision':'rejected','publication_slug':'bad'},
                                 {'decision':'approved','publication_slug':'fine','reviewed_by':M}])
def test_submission_review_payload_is_strict(environment,body):
    client,_=environment
    assert client.post(f'/admin/agent-submissions/{SUBMISSION}/review',headers=auth('admin'),json=body).status_code==422


@pytest.mark.parametrize('token',['a','dev'])
def test_non_admins_cannot_call_any_admin_write_endpoint(environment,token):
    client,remote=environment
    for path,body in [('/admin/agents',{'slug':'new','name':'New','category':'support'}),
                      (f'/admin/connect-requests/{REQUEST}/review',{'decision':'approved'}),
                      (f'/admin/agent-submissions/{SUBMISSION}/review',{'decision':'rejected'})]:
        assert client.post(path,headers=auth(token),json=body).status_code==403
    assert client.patch(f'/admin/agents/{AGENT}',headers=auth(token),json={'name':'X'}).status_code==403
    assert not any('/rpc/' in str(r.url) and 'is_current_session_active' not in str(r.url) for r in remote.requests)


@pytest.mark.parametrize('code,status,expected,public_code',[
    ('23505',409,409,'duplicate_record'),('23514',400,422,'invalid_data'),('23503',409,422,'invalid_reference'),
    ('P0001',400,409,'already_reviewed'),('P0002',404,404,'not_found'),('42501',403,403,'role_forbidden'),
    ('28000',403,401,'session_revoked'),('PGRST202',404,503,'schema_not_ready')])
def test_database_errors_have_stable_public_codes_and_do_not_leak_details(environment,code,status,expected,public_code):
    client,remote=environment
    remote.overrides[('POST','/rest/v1/rpc/create_catalog_agent')]=httpx.Response(status,json={'code':code,'message':'private SQL details'})
    response=client.post('/admin/agents',headers=auth('admin'),json={'slug':'new','name':'New','category':'support'})
    assert response.status_code==expected and response.json()['error']['code']==public_code
    assert 'private SQL' not in response.text


def test_malformed_upstream_data_fails_closed_and_private_responses_are_not_cached(environment):
    client,remote=environment
    remote.overrides[('GET','/rest/v1/agents')]=httpx.Response(200,json={'unexpected':True})
    assert client.get('/agents').status_code==502
    response=client.get('/agent-submissions',headers=auth('dev'))
    assert response.headers['cache-control']=='no-store'
