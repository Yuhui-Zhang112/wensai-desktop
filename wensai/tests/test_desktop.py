import asyncio
import base64
import io
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.db import session


@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=tmp_path/'app.db', file_root=tmp_path/'files', max_file_bytes=30*1024*1024)
    app = create_app(settings)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        yield client


API='/api/v1/desktop'


def upload(client, filename='材料.md', data=None):
    project=client.post(API+'/projects',json={'name':'整合测试'}).raise_for_status().json()
    data=data or '# 教学案例\n\n所有实验只测量一次。只得到一个读数，却声称结论稳定。\n'.encode()
    material=client.post(API+f'/projects/{project["id"]}/materials',files={'file':(filename,data)}).raise_for_status().json()
    return project,material


def preview(client, material, provider='mock', **kwargs):
    return client.post(API+'/scope',json={'materialId':material['id'],'profile':'paper','provider':provider,**kwargs}).raise_for_status().json()


def run(client, material):
    scope=preview(client,material)
    assert scope['text']
    response=client.post(API+f'/tasks/{scope["taskId"]}/confirm',json={'confirmed':True,'textDigest':scope['textDigest']})
    response.raise_for_status()
    for _ in range(200):
        task=client.get(API+f'/tasks/{scope["taskId"]}').raise_for_status().json()
        if task['status'] in {'completed','failed','cancelled'}:
            return task
        import time
        time.sleep(.02)
    pytest.fail('Task timed out')


def test_real_parser_and_c_mock_persist_nullable_result(client):
    project,material=upload(client)
    assert material['previewState']=='ready'
    assert not material['demo']
    task=run(client,material)
    assert task['status']=='completed',task
    assert task['result']['total_score'] is None
    assert task['issues'][0]['severity']=='high'
    assert task['issues'][0]['suggestionKind']=='advice'
    assert task['issues'][0]['location']['line_start']==3
    assert task['issues'][0]['evidence']=='所有实验只测量一次'
    assert task['result']['meta']['provider']=='mock'
    # Entire validated C result is durable, not flattened to A's legacy numeric score.
    with session(client.app.state.settings.db_path) as conn:
        result=json.loads(conn.execute('SELECT result_json FROM desktop_tasks WHERE id=?',(task['id'],)).fetchone()[0])
        assert result['total_score'] is None
        assert conn.execute('SELECT count(*) FROM desktop_audits').fetchone()[0]>0
    issue=task['issues'][0]
    updated=client.patch(API+f'/tasks/{task["id"]}/issues/{issue["id"]}',json={'decision':'accepted'}).raise_for_status().json()
    assert updated['issues'][0]['decision']=='accepted'
    listed=client.get(API+f'/materials/{material["id"]}/tasks').raise_for_status().json()
    assert listed[0]['issues'][0]['decision']=='accepted'


def test_confirmation_is_bound_to_exact_version_and_never_auto_sends(client):
    _,material=upload(client)
    scope=preview(client,material,'deepseek')
    assert scope['destination'].startswith('https://api.deepseek.com/')
    task=client.get(API+f'/tasks/{scope["taskId"]}').raise_for_status().json()
    assert task['status']=='awaiting_confirmation'
    bad=client.post(API+f'/tasks/{scope["taskId"]}/confirm',json={'confirmed':True,'textDigest':'0'*64})
    assert bad.status_code==409
    with session(client.app.state.settings.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM desktop_audits').fetchone()[0]==0


def test_save_version_conflict_and_lossless_markdown_download(client):
    _,material=upload(client)
    scope=preview(client,material)
    raw='# 新标题\n\n**保留 Markdown 标记** 与 [链接](https://example.test)\n'
    changed=client.post(API+f'/materials/{material["id"]}/revisions',json={'blocks':[], 'rawText':raw,'sourceVersionId':material['versionId']}).raise_for_status().json()
    assert changed['versionId']!=material['versionId']
    assert changed['rawText']==raw
    stale=client.post(API+f'/materials/{material["id"]}/revisions',json={'blocks':[], 'rawText':'stale','sourceVersionId':material['versionId']})
    assert stale.status_code==409
    approval=client.post(API+f'/tasks/{scope["taskId"]}/confirm',json={'confirmed':True,'textDigest':scope['textDigest']})
    assert approval.status_code==409
    output=client.post(API+f'/materials/{material["id"]}/exports',json={'format':'text','revisionId':changed['versionId']}).raise_for_status().json()
    assert base64.b64decode(output['contentBase64']).decode()==raw
    original=client.get(API+f'/versions/{material["versionId"]}/download').raise_for_status()
    assert b'**' not in original.content


@pytest.mark.parametrize('filename,profile',[('paper.docx','paper'),('proposal.pdf','proposal'),('defense.pptx','slides')])
def test_real_binary_sample_parses_and_reviews(client,filename,profile):
    root=Path(__file__).resolve().parents[1]
    _,material=upload(client,filename,(root/'task_c_samples'/filename).read_bytes())
    assert material['previewState']=='ready',material
    scope=client.post(API+'/scope',json={'materialId':material['id'],'profile':profile}).raise_for_status().json()
    client.post(API+f'/tasks/{scope["taskId"]}/confirm',json={'confirmed':True,'textDigest':scope['textDigest']}).raise_for_status()
    import time
    for _ in range(200):
        task=client.get(API+f'/tasks/{scope["taskId"]}').raise_for_status().json()
        if task['status'] in {'completed','failed'}: break
        time.sleep(.02)
    assert task['status']=='completed',task
    assert task['result']['meta']['provider']=='mock'
    assert len(task['issues'])==1


def test_durable_seq_websocket_resume_and_archive(client):
    project,material=upload(client)
    task=run(client,material)
    page=client.get(API+f'/tasks/{task["id"]}/events?after=0').raise_for_status().json()
    assert [e['seq'] for e in page['items']]==list(range(1,page['next_after']+1))
    with client.websocket_connect('ws://127.0.0.1'+API+f'/tasks/{task["id"]}/events/ws?after=1') as socket:
        assert socket.receive_json()['seq']==2
    client.delete(API+f'/projects/{project["id"]}').raise_for_status()
    assert client.get(API+'/projects').json()==[]
    # Archive deliberately retains managed originals; there is no recursive file deletion.
    assert list(client.app.state.settings.file_root.rglob('*.md'))


def test_format_rules_return_real_b_report_without_model(client):
    root=Path(__file__).resolve().parents[1]
    _,material=upload(client,'academic_errors.docx',(root/'task_b_samples/academic_errors.docx').read_bytes())
    result=client.get(API+f'/materials/{material["id"]}/format?profile=paper').raise_for_status().json()
    assert result['versionId']==material['versionId']
    assert result['report']['summary']['fail']>0
    with session(client.app.state.settings.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM desktop_audits').fetchone()[0]==0


def test_cancel_running_mock_never_saves_partial_result(client,monkeypatch):
    from app.review_agent.provider import MockProvider
    started=__import__('threading').Event()
    async def slow(self,chunk,**kwargs):
        started.set()
        await asyncio.sleep(10)
        return '{"dimensions":[],"issues":[]}'
    monkeypatch.setattr(MockProvider,'complete',slow)
    _,material=upload(client)
    scope=preview(client,material)
    client.post(API+f'/tasks/{scope["taskId"]}/confirm',json={'confirmed':True,'textDigest':scope['textDigest']}).raise_for_status()
    assert started.wait(2)
    cancelled=client.post(API+f'/tasks/{scope["taskId"]}/cancel').raise_for_status().json()
    assert cancelled['status'] in {'cancelling','cancelled'}
    import time
    for _ in range(100):
        task=client.get(API+f'/tasks/{scope["taskId"]}').raise_for_status().json()
        if task['status']=='cancelled': break
        time.sleep(.02)
    assert task['status']=='cancelled'
    assert task['result'] is None


def test_origin_policy_and_duplicate_confirmation(client):
    assert client.get(API+'/projects',headers={'Origin':'https://untrusted.example'}).status_code==403
    _,material=upload(client)
    task=run(client,material)
    duplicate=client.post(API+f'/tasks/{task["id"]}/confirm',json={'confirmed':True,'textDigest':'0'*64})
    assert duplicate.status_code==409


def test_report_and_decisions_survive_service_restart(tmp_path):
    settings=Settings(db_path=tmp_path/'restart.db',file_root=tmp_path/'files')
    with TestClient(create_app(settings),base_url='http://127.0.0.1') as client:
        _,material=upload(client)
        task=run(client,material)
        issue=task['issues'][0]
        client.patch(API+f'/tasks/{task["id"]}/issues/{issue["id"]}',json={'decision':'edited','editedText':'用户拟定的新正文'}).raise_for_status()
    with TestClient(create_app(settings),base_url='http://127.0.0.1') as client:
        restored=client.get(API+f'/tasks/{task["id"]}').raise_for_status().json()
        assert restored['status']=='completed'
        assert restored['issues'][0]['editedText']=='用户拟定的新正文'
        assert restored['result']['total_score'] is None
