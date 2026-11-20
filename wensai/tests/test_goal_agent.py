import asyncio
import json
import time

import pytest
from app.agent_runtime import Action, ModelPolicy
from app.db import session
from test_desktop import API, client, upload


def start(client, goal='重点检查论证与证据', **extra):
    _,material=upload(client)
    scope=client.post(API+'/scope',json={'materialId':material['id'],'profile':'paper','executionMode':'agent','goal':goal,**extra}).raise_for_status().json()
    assert scope['intentDigest'] and scope['goal']==goal
    client.post(API+f'/tasks/{scope["taskId"]}/confirm',json={'confirmed':True,'textDigest':scope['textDigest'],'intentDigest':scope['intentDigest']}).raise_for_status()
    return material,scope


def finish(client, scope):
    for _ in range(300):
        task=client.get(API+f'/tasks/{scope["taskId"]}').raise_for_status().json()
        if task['status'] in {'completed','failed','cancelled'}:
            return task
        time.sleep(.02)
    pytest.fail('goal agent timed out')


def test_real_tools_and_c_mock_trace_are_durable(client):
    material,scope=start(client)
    task=finish(client,scope)
    assert task['status']=='completed',task
    agent=task['agent']
    assert agent['mode']=='agent' and agent['termination']=='finished'
    actions=[s['action'] for s in agent['steps']]
    assert actions==['plan','inspect_scope','plan','search_standards','plan','review_content','plan','finish']
    assert all(s['status']=='completed' for s in agent['steps'])
    assert task['result']['meta']['provider']=='mock'
    assert task['issues'][0]['evidence']=='所有实验只测量一次'
    with session(client.app.state.settings.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM agent_steps WHERE task_id=?',(task['id'],)).fetchone()[0]==8
    report=client.post(API+f'/materials/{material["id"]}/exports',json={'taskId':task['id'],'format':'report'}).raise_for_status().json()
    import base64
    assert json.loads(base64.b64decode(report['contentBase64']))['task']['agent']['steps']==agent['steps']


def test_goal_changes_tool_choice_format_only_never_calls_c(client,monkeypatch):
    from app.review_agent.provider import MockProvider
    async def forbidden(*args,**kwargs):
        pytest.fail('format-only goal must not call content provider')
    monkeypatch.setattr(MockProvider,'complete',forbidden)
    _,scope=start(client,'只做格式检查')
    task=finish(client,scope)
    assert task['status']=='completed',task
    actions=[s['action'] for s in task['agent']['steps']]
    assert 'check_format' in actions and 'review_content' not in actions
    assert task['issues']==[] and task['result']['total_score'] is None


def test_task_intent_confirmation_required_and_goal_not_mutable(client):
    _,m=upload(client)
    scope=client.post(API+'/scope',json={'materialId':m['id'],'profile':'paper','executionMode':'agent','goal':'查证据'}).raise_for_status().json()
    for digest in [None,'0'*64]:
        response=client.post(API+f'/tasks/{scope["taskId"]}/confirm',json={'confirmed':True,'textDigest':scope['textDigest'],'intentDigest':digest})
        assert response.status_code==409
    assert client.post(API+'/scope',json={'materialId':m['id'],'profile':'paper','executionMode':'agent','goal':' '}).status_code==422


def test_agent_never_observes_unselected_text(client):
    _,m=upload(client,data='# 可公开标题\n\n所有实验只测量一次。\n\nPRIVATE_SENTINEL_827319'.encode())
    selected=[b['id'] for b in m['blocks'] if '所有实验只测量一次' in b['text']]
    scope=client.post(API+'/scope',json={'materialId':m['id'],'profile':'paper','executionMode':'agent','goal':'查证据','blockIds':selected}).raise_for_status().json()
    assert 'PRIVATE_SENTINEL_827319' not in json.dumps(scope)
    client.post(API+f'/tasks/{scope["taskId"]}/confirm',json={'confirmed':True,'textDigest':scope['textDigest'],'intentDigest':scope['intentDigest']}).raise_for_status()
    task=finish(client,scope)
    assert task['status']=='completed'
    assert 'PRIVATE_SENTINEL_827319' not in json.dumps(task,ensure_ascii=False)


def test_adaptive_policy_sees_observation_then_asks_for_input(client,monkeypatch):
    from app.agent_runtime import OfflinePolicy
    states=[]
    async def choose(self,state):
        states.append(state)
        if not state['observations']: return Action(action='inspect_scope')
        assert '所有实验只测量一次' in state['observations'][0]['observation']
        return Action(action='ask_user',answer='请补充独立重复次数和对应赛事要求。')
    monkeypatch.setattr(OfflinePolicy,'choose',choose)
    m,scope=start(client)
    task=finish(client,scope)
    assert task['status']=='completed' and task['agent']['termination']=='needs_input'
    next_scope=client.post(API+'/scope',json={'materialId':m['id'],'profile':'paper','executionMode':'agent','goal':'补充：已重复3次','parentTaskId':task['id']}).raise_for_status().json()
    assert '请补充独立重复次数' in next_scope['context']
    assert next_scope['taskId']!=task['id']
    assert client.get(API+f'/tasks/{task["id"]}').json()['agent']['answer']==task['agent']['answer']
    assert client.get(API+f'/tasks/{next_scope["taskId"]}').json()['status']=='awaiting_confirmation'


def test_policy_repeated_tools_hit_budget_without_looping_forever(client,monkeypatch):
    from app.agent_runtime import OfflinePolicy
    async def choose(self,state): return Action(action='inspect_scope')
    monkeypatch.setattr(OfflinePolicy,'choose',choose)
    _,scope=start(client)
    task=finish(client,scope)
    assert task['status']=='completed' and task['agent']['termination']=='step_limit'
    assert len(task['agent']['steps'])==16
    assert any(s['status']=='failed' for s in task['agent']['steps'])


def test_model_policy_whitelist_and_model_transport_without_keys():
    class Provider:
        async def complete(self,request,**kwargs):
            messages=request.messages()
            assert '白名单' in messages[0]['content']
            assert json.loads(messages[1]['content'])['goal']=='查证据'
            return '{"action":"inspect_scope","query":"","focus":"","answer":""}'
    assert asyncio.run(ModelPolicy(Provider()).choose({'goal':'查证据'})).action=='inspect_scope'
    class Malicious:
        async def complete(self,*args,**kwargs):
            return '{"action":"run_shell","query":"del all"}'
    from app.review_agent import ReviewError
    with pytest.raises(ReviewError):
        asyncio.run(ModelPolicy(Malicious()).choose({'goal':'查证据'}))


def test_cancel_during_agent_plan_leaves_no_running_steps(client,monkeypatch):
    from app.agent_runtime import OfflinePolicy
    started=__import__('threading').Event()
    async def slow(self,state):
        started.set()
        await asyncio.sleep(10)
        return Action(action='inspect_scope')
    monkeypatch.setattr(OfflinePolicy,'choose',slow)
    _,scope=start(client)
    assert started.wait(2)
    client.post(API+f'/tasks/{scope["taskId"]}/cancel').raise_for_status()
    task=finish(client,scope)
    assert task['status']=='cancelled' and task['result'] is None
    assert all(s['status']!='running' for s in task['agent']['steps'])


@pytest.mark.parametrize('filename,profile',[('paper.docx','paper'),('proposal.pdf','proposal'),('defense.pptx','slides')])
def test_agent_scoped_format_tool_supports_binary_formats(client,filename,profile):
    from pathlib import Path
    _,m=upload(client,filename,(Path(__file__).resolve().parents[1]/'task_c_samples'/filename).read_bytes())
    scope=client.post(API+'/scope',json={'materialId':m['id'],'profile':profile,'executionMode':'agent','goal':'只检查格式'}).raise_for_status().json()
    client.post(API+f'/tasks/{scope["taskId"]}/confirm',json={'confirmed':True,'textDigest':scope['textDigest'],'intentDigest':scope['intentDigest']}).raise_for_status()
    task=finish(client,scope)
    assert task['status']=='completed',task
    checked=next(s for s in task['agent']['steps'] if s['action']=='check_format')
    assert checked['status']=='completed',checked
    assert checked['observation']['report']['summary']['needs_review']>0


def test_deepseek_model_drives_loop_using_fake_http_no_real_key(client,monkeypatch):
    import httpx
    from app.review_agent.provider import DeepSeekProvider
    import app.desktop_engine as engine
    calls=[]
    class Credentials:
        def read(self): return 'synthetic-test-key'
    async def handler(request):
        body=json.loads(request.content)
        calls.append(body)
        state=json.loads(body['messages'][1]['content'])
        if not state['observations']:
            action=Action(action='inspect_scope')
        else:
            assert '所有实验只测量一次' in state['observations'][0]['observation']
            action=Action(action='ask_user',answer='请提供本届评分细则。')
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':action.model_dump_json()}}]})
    monkeypatch.setattr(engine,'DeepSeekProvider',lambda config:DeepSeekProvider(config,credentials=Credentials(),transport=httpx.MockTransport(handler)))
    _,scope=start(client,provider='deepseek')
    task=finish(client,scope)
    assert task['status']=='completed',task
    assert task['provider']=='deepseek' and task['agent']['termination']=='needs_input'
    assert len(calls)==2
    assert all(s['observation'].get('mode')=='model_json_decision' for s in task['agent']['steps'] if s['action']=='plan')


def test_missing_model_credentials_fail_without_fake_success(client,monkeypatch):
    from app.review_agent import ReviewError
    import app.desktop_engine as engine
    class Broken:
        name,model='deepseek','deepseek-flash'
        async def complete(self,*args,**kwargs): raise ReviewError('credential_missing','未配置系统凭据。')
    monkeypatch.setattr(engine,'DeepSeekProvider',lambda config:Broken())
    _,scope=start(client,provider='deepseek')
    task=finish(client,scope)
    assert task['status']=='failed' and task['result'] is None
    assert task['agent']['steps'][0]['observation']['code']=='credential_missing'


def test_followup_displays_context_and_blocks_wrong_material(client):
    m,scope=start(client)
    task=finish(client,scope)
    _,other=upload(client)
    response=client.post(API+'/scope',json={'materialId':other['id'],'profile':'paper','executionMode':'agent','goal':'继续','parentTaskId':task['id']})
    assert response.status_code==409
    follow=client.post(API+'/scope',json={'materialId':m['id'],'profile':'paper','executionMode':'agent','goal':'只检查格式','parentTaskId':task['id']}).raise_for_status().json()
    assert 'previous_goal' in follow['context'] and follow['intentDigest']!=scope['intentDigest']
    client.post(API+f'/tasks/{follow["taskId"]}/confirm',json={'confirmed':True,'textDigest':follow['textDigest'],'intentDigest':follow['intentDigest']}).raise_for_status()
    assert finish(client,follow)['agent']['parentTaskId']==task['id']
