from datetime import UTC, datetime
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import jwt
import pytest

from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.test_auth import A, auth
from backend.tests.test_marketplace import AGENT, MarketplaceFake, NOW, card, connection

SECRET = "engine-test-signing-key-0123456789abcdef"
ENGINE_RUN = "60000000-0000-4000-8000-000000000001"
ENGINE_FILE = "70000000-0000-4000-8000-000000000001"


def run_row(**changes):
    return dict(id=str(uuid4()),engine_run_id=None,company_id=A,user_id=A,agent_id=AGENT,engine_slug="marketing",
        agent_version=None,status="running",language=None,mode=None,model=None,input_tokens=None,output_tokens=None,
        total_tokens=None,estimated_cost=None,currency="USD",execution_time_ms=None,http_status=None,error_code=None,
        request_id=None,file_count=0,source_count=0,created_at=NOW,updated_at=NOW,**changes)


def file_row(**changes):
    file_id=str(uuid4())
    return {"id":file_id,"company_id":A,"user_id":A,"bucket_id":"agent-files",
        "object_path":f"{A}/{A}/{file_id}/document.txt","original_name":"brief.txt","mime_type":"text/plain",
        "size_bytes":5,"purpose":"brief","engine_file_id":None,"engine_synced_at":None,
        "deletion_requested_at":None,"created_at":NOW,"updated_at":NOW,**changes}


def execution(**changes):
    return {"run_id":ENGINE_RUN,"agent":"marketing","agent_version":"1.0.0","status":"success",
        "response":"Demonstration only","language":"ru","sources":[],"usage":{
            "input_tokens":10,"output_tokens":5,"total_tokens":15,"estimated_cost":0.0,"currency":"USD"},
        "execution_time_ms":10,"mode":"mock","model":"mock","data":{},"warnings":["mock_mode"],**changes}


class RuntimeFake(MarketplaceFake):
    def __init__(self):
        super().__init__()
        self.records["agents"][0]["accepted_file_purposes"]=["brief","knowledge_base"]
        self.records["connect_requests"][0]=connection(status="approved",reviewed_by=A,reviewed_at=NOW)
        self.records.update(agent_runs=[],agent_files=[])
        self.blobs={}
        self.fail_initial=False
        self.fail_finalize=False
        self.fail_file_sync=False

    def __call__(self, request):
        table=request.url.path.removeprefix('/rest/v1/')
        is_secret=request.headers.get('apikey')=='sb_secret_test'
        if request.url.path.startswith('/storage/'):
            assert is_secret
            self.requests.append(request)
            path=request.url.path.removeprefix('/storage/v1/object/agent-files/')
            if request.method=='POST':
                self.blobs[path]=request.content
                return httpx.Response(200,json={'Key':path})
            if request.method=='GET':
                return httpx.Response(200,content=self.blobs[path])
            if request.method=='DELETE':
                for prefix in json.loads(request.content)['prefixes']:
                    self.blobs.pop(prefix,None)
                return httpx.Response(200,json=[])
        if table not in {'agent_runs','agent_files'}:
            return super().__call__(request)
        self.requests.append(request)
        if request.method=='GET':
            assert not is_secret
        else:
            assert is_secret and 'authorization' not in request.headers
        if table=='agent_runs' and ((request.method=='POST' and self.fail_initial) or (request.method=='PATCH' and self.fail_finalize)):
            return httpx.Response(503,json={'message':'private details'})
        if table=='agent_files' and request.method=='PATCH' and self.fail_file_sync:
            return httpx.Response(503,json={'message':'private details'})
        rows=self.records[table]
        if request.method=='POST':
            data=json.loads(request.content)
            row=run_row() if table=='agent_runs' else file_row()
            row.update(data)
            rows.append(row)
            return httpx.Response(201,json=[row])
        matched=list(rows)
        for key,value in request.url.params.items():
            if value.startswith('eq.'):
                matched=[row for row in matched if str(row.get(key))==value[3:]]
        if request.method=='PATCH':
            for row in matched:
                row.update(json.loads(request.content))
                if table=='agent_runs' and row['input_tokens'] is not None:
                    row['total_tokens']=row['input_tokens']+row['output_tokens']
            return httpx.Response(200,json=matched)
        if request.method=='DELETE':
            self.records[table]=[row for row in rows if row not in matched]
            return httpx.Response(204)
        return httpx.Response(200,json=matched[int(request.url.params.get('offset',0)):][:int(request.url.params.get('limit',100))])


class EngineFake:
    def __init__(self):
        self.requests=[]
        self.files=set()
        self.run_response=httpx.Response(200,json=execution())
        self.upload_response=None
        self.delete_error=False
        self.run_metadata=None

    def __call__(self,request):
        self.requests.append(request)
        if request.url.path=='/health':
            return httpx.Response(200,json={'status':'ok','version':'1.0.0','llm_provider':'mock','llm_mode':'mock','llm_billing':'none',
                                           'agents':['marketing','support','hr'],'private_field':'never-output'})
        claims=jwt.decode(request.headers['authorization'].removeprefix('Bearer '),SECRET,
                          algorithms=['HS256'],audience='ai-engine',issuer='marketplace-backend')
        assert claims['sub']==A and claims['company_id']==A and claims['role']=='admin'
        assert claims['exp']-claims['iat']==300
        if request.url.path.endswith('/run'):
            if isinstance(self.run_response,Exception):
                raise self.run_response
            return self.run_response
        if request.url.path.startswith('/runs/'):
            return httpx.Response(200,json=self.run_metadata) if self.run_metadata else httpx.Response(404,json={'error':{'code':'run_not_found'}})
        if request.url.path=='/files/upload':
            if self.upload_response is not None:
                return self.upload_response
            self.files.add(ENGINE_FILE)
            return httpx.Response(201,json={'id':ENGINE_FILE})
        file_id=request.url.path.rsplit('/',1)[-1]
        if request.method=='DELETE' and self.delete_error:
            return httpx.Response(503,json={'error':{'code':'internal_error'}})
        if file_id not in self.files:
            return httpx.Response(404,json={'error':{'code':'file_not_found'}})
        if request.method=='DELETE':
            self.files.remove(file_id)
            return httpx.Response(204)
        return httpx.Response(200,json={'id':file_id})


@pytest.fixture
def environment():
    remote,engine=RuntimeFake(),EngineFake()
    settings=Settings(supabase_url='https://project.supabase.co',supabase_publishable_key='sb_publishable_test',
        supabase_secret_key='sb_secret_test',engine_jwt_secret=SECRET)
    with TestClient(create_app(settings,transport=httpx.MockTransport(remote),engine_transport=httpx.MockTransport(engine))) as client:
        yield client,remote,engine


def test_run_requires_approval_uses_engine_token_and_persists_only_metadata(environment):
    client,remote,engine=environment
    response=client.post('/agents/marketing/run',headers=auth(),json={'message':'private user prompt','history':[{'role':'user','content':'private history'}]})
    assert response.status_code==200 and response.json()['audit_saved'] is True
    row=remote.records['agent_runs'][0]
    assert row['status']=='success' and row['engine_run_id']==ENGINE_RUN and row['total_tokens']==15
    assert row['request_id']==response.headers['x-request-id']
    assert not any(key in row for key in ['message','response','history','options','sources','data'])
    assert 'private user prompt' not in json.dumps(row)
    assert len([r for r in engine.requests if r.url.path.endswith('/run')])==1
    assert client.get('/runs',headers=auth()).json()['items'][0]['id']==row['id']
    assert client.get(f"/runs/{row['id']}",headers=auth()).status_code==200
    assert client.get('/runs',headers=auth('admin')).status_code==403


@pytest.mark.parametrize('token',['dev','admin'])
def test_non_business_roles_cannot_run_or_upload(environment,token):
    client,remote,engine=environment
    assert client.post('/agents/marketing/run',headers=auth(token),json={'message':'Test'}).status_code==403
    assert client.post('/files/upload',headers=auth(token),data={'purpose':'brief'},files={'file':('brief.txt',b'Hello','text/plain')}).status_code==403
    assert engine.requests==[] and remote.records['agent_runs']==[]


def test_unapproved_and_unpublished_agents_never_reach_engine(environment):
    client,remote,engine=environment
    remote.records['connect_requests'][0]['status']='pending'
    assert client.post('/agents/marketing/run',headers=auth(),json={'message':'Test'}).status_code==403
    remote.records['agents'][0]['status']='coming_soon'
    assert client.post('/agents/marketing/run',headers=auth(),json={'message':'Test'}).status_code==404
    assert engine.requests==[]


@pytest.mark.parametrize('body',[{'message':'Test','company_id':A},{'message':'Test','user_id':A},{'message':'Test','language':'kz'},
    {'message':''},{'message':'Test','file_ids':['bad-id']},{'message':'Test','file_ids':[ENGINE_FILE,ENGINE_FILE]}])
def test_run_identity_language_and_file_inputs_are_strict(environment,body):
    client,_,engine=environment
    assert client.post('/agents/marketing/run',headers=auth(),json=body).status_code==422
    assert engine.requests==[]


def test_missing_server_key_and_failed_initial_audit_prevent_execution(environment):
    client,remote,engine=environment
    remote.fail_initial=True
    assert client.post('/agents/marketing/run',headers=auth(),json={'message':'Test'}).status_code==503
    assert engine.requests==[]
    client.app.state.runtime_store.settings=client.app.state.runtime_store.settings.model_copy(update={'supabase_secret_key':None})
    response=client.post('/agents/marketing/run',headers=auth(),json={'message':'Test'})
    assert response.json()['error']['code']=='runtime_storage_not_configured'
    assert engine.requests==[]


def test_failed_final_audit_returns_result_without_retrying_engine(environment):
    client,remote,engine=environment
    remote.fail_finalize=True
    response=client.post('/agents/marketing/run',headers=auth(),json={'message':'Test'})
    assert response.status_code==200 and response.json()['audit_saved'] is False
    assert remote.records['agent_runs'][0]['status']=='running'
    assert len([r for r in engine.requests if r.url.path.endswith('/run')])==1


@pytest.mark.parametrize('status,code,expected',[(422,'resume_required',422),(429,'daily_limit_exceeded',429),(401,'invalid_credentials',502)])
def test_engine_errors_are_logged_and_preserve_safe_run_id_and_retry_after(environment,status,code,expected):
    client,remote,engine=environment
    engine.run_response=httpx.Response(status,headers={'Retry-After':'30'},json={
        'error':{'code':code,'message':'private echoed input','details':{'run_id':ENGINE_RUN,'private':'not-output'}}})
    response=client.post('/agents/marketing/run',headers=auth(),json={'message':'Test'})
    assert response.status_code==expected
    assert response.json()['error']['details']['engine_run_id']==ENGINE_RUN
    assert 'private' not in response.text
    assert response.headers['Retry-After']=='30'
    assert remote.records['agent_runs'][0]['status']=='error'
    assert len([r for r in engine.requests if r.url.path.endswith('/run')])==1
    assert remote.records['agent_runs'][0]['http_status']==status


def test_ambiguous_timeout_is_recorded_and_never_retried(environment):
    client,remote,engine=environment
    engine.run_response=httpx.ReadTimeout('internal detail')
    response=client.post('/agents/marketing/run',headers=auth(),json={'message':'Test'})
    assert response.status_code==504 and response.json()['error']['code']=='engine_timeout'
    assert remote.records['agent_runs'][0]['status']=='engine_unreachable'
    assert remote.records['agent_runs'][0]['engine_run_id'] is None
    assert len(engine.requests)==1


def test_error_reconciliation_copies_metadata_without_reexecuting(environment):
    client,remote,engine=environment
    engine.run_response=httpx.Response(422,json={'error':{'code':'resume_required','details':{'run_id':ENGINE_RUN}}})
    engine.run_metadata={'id':ENGINE_RUN,'agent_slug':'marketing','agent_version':'1.0.0','status':'rejected',
        'language':'ru','llm_mode':'none','model':None,'input_tokens':0,'output_tokens':0,
        'estimated_cost':0.0,'execution_time_ms':3,'source_count':0}
    response=client.post('/agents/marketing/run',headers=auth(),json={'message':'Test'})
    assert response.status_code==422
    assert remote.records['agent_runs'][0]['status']=='rejected'
    assert remote.records['agent_runs'][0]['input_tokens']==0
    assert len([r for r in engine.requests if r.method=='POST'])==1


@pytest.mark.parametrize('data',[{},execution(agent='hr'),execution(usage={'input_tokens':1,'output_tokens':1,'total_tokens':9,'estimated_cost':0,'currency':'USD'})])
def test_invalid_engine_contract_fails_closed(environment,data):
    client,remote,engine=environment
    engine.run_response=httpx.Response(200,json=data)
    assert client.post('/agents/marketing/run',headers=auth(),json={'message':'Test'}).status_code==502
    assert remote.records['agent_runs'][0]['status']=='error'


def test_upload_stores_original_and_metadata_then_synchronizes_to_engine(environment):
    client,remote,engine=environment
    response=client.post('/files/upload',headers=auth(),data={'purpose':'brief'},files={'file':('brief.txt',b'Hello','text/plain')})
    assert response.status_code==201
    row=response.json()
    assert row['engine_file_id']==ENGINE_FILE and row['size_bytes']==5
    assert row['object_path']==f"{A}/{A}/{row['id']}/document.txt"
    assert remote.blobs[row['object_path']]==b'Hello'
    assert b'Hello' in engine.requests[0].content
    assert client.get('/files',headers=auth()).json()['items'][0]['id']==row['id']
    assert client.get(f"/files/{row['id']}/download",headers=auth()).content==b'Hello'


def test_run_maps_platform_file_ids_and_recovers_stale_engine_copy_before_execution(environment):
    client,remote,engine=environment
    row=file_row(engine_file_id=ENGINE_FILE,engine_synced_at=NOW)
    remote.records['agent_files'].append(row)
    remote.blobs[row['object_path']]=b'Hello'
    response=client.post('/agents/marketing/run',headers=auth(),json={'message':'Test','file_ids':[row['id']]})
    assert response.status_code==200
    assert [r.url.path for r in engine.requests]==[f'/files/{ENGINE_FILE}','/files/upload','/agents/marketing/run']
    assert json.loads(engine.requests[-1].content)['file_ids']==[ENGINE_FILE]
    assert remote.records['agent_runs'][0]['file_count']==1


def test_foreign_deleting_or_wrong_purpose_files_cannot_reach_engine(environment):
    client,remote,engine=environment
    foreign=file_row(company_id=str(uuid4()),user_id=str(uuid4()))
    remote.records['agent_files'].append(foreign)
    assert client.get(f"/files/{foreign['id']}",headers=auth()).status_code==404
    assert client.post('/agents/marketing/run',headers=auth(),json={'message':'Test','file_ids':[foreign['id']]}).status_code==404
    row=file_row(purpose='resume')
    remote.records['agent_files'].append(row)
    assert client.post('/agents/marketing/run',headers=auth(),json={'message':'Test','file_ids':[row['id']]}).status_code==422
    row.update(purpose='brief',deletion_requested_at=NOW)
    assert client.post('/agents/marketing/run',headers=auth(),json={'message':'Test','file_ids':[row['id']]}).status_code==409
    assert engine.requests==[]


def test_deletion_marks_tombstone_then_removes_both_copies_and_row(environment):
    client,remote,engine=environment
    row=file_row(engine_file_id=ENGINE_FILE,engine_synced_at=NOW)
    remote.records['agent_files'].append(row)
    remote.blobs[row['object_path']]=b'Hello'
    engine.files.add(ENGINE_FILE)
    engine.delete_error=True
    assert client.delete(f"/files/{row['id']}",headers=auth()).status_code==503
    assert row['deletion_requested_at'] is not None and row['object_path'] in remote.blobs
    engine.delete_error=False
    assert client.delete(f"/files/{row['id']}",headers=auth()).status_code==204
    assert remote.records['agent_files']==[] and remote.blobs=={} and engine.files==set()


def test_engine_upload_failure_keeps_private_original_for_retry_or_deletion(environment):
    client,remote,engine=environment
    engine.upload_response=httpx.Response(422,json={'error':{'code':'file_type_mismatch'}})
    response=client.post('/files/upload',headers=auth(),data={'purpose':'brief'},files={'file':('brief.pdf',b'not a PDF','application/pdf')})
    assert response.status_code==422
    assert response.json()['error']['details']['original_saved'] is True
    assert len(remote.records['agent_files'])==1 and len(remote.blobs)==1


def test_failed_file_mapping_cleans_engine_copy_and_keeps_original(environment):
    client,remote,engine=environment
    remote.fail_file_sync=True
    response=client.post('/files/upload',headers=auth(),data={'purpose':'brief'},files={'file':('brief.txt',b'Hello','text/plain')})
    assert response.status_code==503 and response.json()['error']['details']['original_saved'] is True
    assert engine.files==set() and len(remote.blobs)==1
    assert remote.records['agent_files'][0]['engine_file_id'] is None


@pytest.mark.parametrize('filename,content,status',[('bad.exe',b'123',415),('empty.txt',b'',422),('large.txt',b'x'*(10*1024*1024+1),413)],
                         ids=['invalid-type','empty','too-large'])
def test_file_type_empty_and_size_limits(environment,filename,content,status):
    client,remote,_=environment
    assert client.post('/files/upload',headers=auth(),data={'purpose':'brief'},files={'file':(filename,content)}).status_code==status
    assert remote.blobs=={}


def test_body_limit_rejects_large_json_before_parsing(environment):
    client,_,_=environment
    response=client.post('/agents/marketing/run',headers=auth(),content=b'x'*(512*1024+1))
    assert response.status_code==413


def test_engine_health_is_public_and_exposes_no_private_fields(environment):
    client,_,_=environment
    response=client.get('/engine/health')
    assert response.status_code==200 and response.json()['llm_provider']=='mock'
    assert 'private_field' not in response.json()
