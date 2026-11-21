"""Exercise Backend 2 against the real local engine, with isolated fake Supabase.

No real Supabase account/key is needed. Mocked Auth/Storage/audit are explicitly
kept separate from the real engine, JWT validation, PDF/DOCX parsing and RAG.
"""
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import httpx

from backend.app.config import Settings
from backend.app.engine_client import EngineClient
from backend.app.main import create_app
from backend.app.models import Principal
from backend.tests.test_auth import auth
from backend.tests.test_execution import RuntimeFake
from backend.tests.test_marketplace import NOW, card, connection


def main():
    root=Path(__file__).resolve().parents[1]
    actor=str(uuid4())
    settings=Settings.from_env().model_copy(update={"supabase_secret_key":None})
    # Fake Supabase accepts only this test key. It is never sent to a real server.
    settings=Settings(**{**settings.model_dump(),"supabase_url":"https://project.supabase.co",
                         "supabase_publishable_key":"sb_publishable_test","supabase_secret_key":"sb_secret_test"})
    principal=Principal(user_id=UUID(actor),email=None,role='business',company_id=UUID(actor),
                        display_name='Synthetic Integration User',company_name='Fictional Integration Company')
    engine_headers={'Authorization':f'Bearer {EngineClient(settings,None).token(principal)}'}
    with httpx.Client(base_url=settings.engine_url,timeout=30,trust_env=False) as engine_http:
        metadata=engine_http.get('/agents',headers=engine_headers).json()['agents']
    remote=RuntimeFake()
    remote.profiles['a']['id']=actor
    remote.records['agents']=[]
    remote.records['connect_requests']=[]
    for info in metadata:
        agent_id=str(uuid4())
        remote.records['agents'].append(card(id=agent_id,slug=info['slug'],name=info['name'],category=info['category'],
            engine_slug=info['slug'],accepted_file_purposes=info['accepted_file_purposes']))
        remote.records['connect_requests'].append(connection(id=str(uuid4()),agent_id=agent_id,company_id=actor,requested_by=actor,
            status='approved',reviewed_by=actor,reviewed_at=NOW))
    uploaded=[]
    checks=[]
    def expect(response,status,step):
        if response.status_code!=status:
            code=response.json().get('error',{}).get('code','unknown')
            raise RuntimeError(f'{step}: HTTP {response.status_code}, code={code}')
        checks.append(step)
        return response.json() if status!=204 else None
    with TestClient(create_app(settings,transport=httpx.MockTransport(remote))) as client:
        expect(client.get('/engine/health'),200,'real_engine_health')
        result=expect(client.post('/agents/marketing/run',headers=auth(),json={
            'message':'Create a content plan for a fictional coffee shop.','language':'en'}),200,'marketing_run')
        assert result['execution']['mode']=='mock' and result['audit_saved']
        kb=expect(client.post('/files/upload',headers=auth(),data={'purpose':'knowledge_base'},files={
            'file':('knowledge.txt','Доставка по городу стоит 1000 тенге. Доставка занимает два дня.'.encode(),'text/plain')}),201,'knowledge_base_upload')
        uploaded.append(kb)
        result=expect(client.post('/agents/support/run',headers=auth(),json={
            'message':'Сколько стоит доставка?','language':'ru','file_ids':[kb['id']]}),200,'support_rag_run')
        assert result['execution']['sources'] and result['execution']['status']=='success'
        resume=expect(client.post('/files/upload',headers=auth(),data={'purpose':'resume'},files={
            'file':('resume.docx',(root/'.run/fixtures/fictional-resume.docx').read_bytes(),
                     'application/vnd.openxmlformats-officedocument.wordprocessingml.document')}),201,'docx_upload')
        uploaded.append(resume)
        result=expect(client.post('/agents/hr/run',headers=auth(),json={'message':'Summarize the uploaded resume.',
            'language':'en','file_ids':[resume['id']],'options':{'task':'resume_summary'}}),200,'hr_docx_run')
        assert result['execution']['status']=='success'
        pdf=expect(client.post('/files/upload',headers=auth(),data={'purpose':'brief'},files={
            'file':('brief.pdf',(root/'.run/fixtures/fictional-brief.pdf').read_bytes(),'application/pdf')}),201,'pdf_upload')
        uploaded.append(pdf)
        expect(client.post('/agents/marketing/run',headers=auth(),json={'message':'Create a content plan from the attached brief.',
            'language':'en','file_ids':[pdf['id']]}),200,'marketing_pdf_run')
        bad=client.post('/agents/hr/run',headers=auth(),json={'message':'Summarize the uploaded resume.','options':{'task':'resume_summary'}})
        expect(bad,422,'hr_missing_resume_logged')
        assert bad.json()['error']['details']['engine_run_id']
        history=expect(client.get('/runs',headers=auth()),200,'platform_run_history')
        assert len(history['items'])==5 and sum(row['status']=='success' for row in history['items'])==4
        for row in uploaded:
            expect(client.delete(f"/files/{row['id']}",headers=auth()),204,'file_deleted_from_both_systems')
        assert remote.records['agent_files']==[] and remote.blobs=={}
    print({'passed':len(checks),'real_engine':True,'real_pdf_docx':True,'real_rag':True,'llm_mode':'mock',
           'supabase':'isolated test double','run_records':len(remote.records['agent_runs'])})


if __name__=='__main__':
    main()
