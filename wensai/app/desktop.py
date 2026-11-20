"""Desktop API: D DTO mapping, immutable versions, explicit scope approval.

Business writes stay in A. B/C packages are imported rather than their cloud backend.
"""
import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .common import ApiError, get_db
from .db import new_id, now, session, transaction
from . import materials, storage
from .desktop_engine import append_event, change
from .material_review import parse_document, validate_document, load_profile, check_document, MaterialError
from .material_review.model import Document, Block, Source
from .review_agent import TaskInput, Selection, TextSlice, Approval, ReviewError, SystemCredentialStore, preview_scope
from .review_agent.scope import ALLOWED_TEXT
from .review_agent.skills import select_skill

router = APIRouter(prefix='/desktop', tags=['桌面整合'])
PROFILES = {'paper': 'academic-paper-v1', 'proposal': 'competition-proposal-v1', 'slides': 'ppt-defense-v1'}


def material_row(conn, material_id):
    row = conn.execute('SELECT m.* FROM materials m JOIN projects p ON p.id=m.project_id WHERE m.id=? AND m.archived=0 AND p.archived=0', (material_id,)).fetchone()
    if row is None:
        raise ApiError(404, 'MATERIAL_NOT_FOUND', '材料不存在或已移除。')
    return row


def version_row(conn, version_id):
    row = conn.execute(materials.VERSION_QUERY + ' WHERE v.id=?', (version_id,)).fetchone()
    if row is None:
        raise ApiError(404, 'VERSION_NOT_FOUND', '版本不存在。')
    return row


def parsed(conn, settings, version_id):
    version = version_row(conn, version_id)
    row = conn.execute('SELECT f.relative_path FROM files f WHERE f.id=?', (version['file_id'],)).fetchone()
    path = storage.resolve_file(settings.file_root, version['project_id'], row['relative_path'])
    # A verifies managed bytes against their immutable version before parsing or reviewing.
    if hashlib.sha256(path.read_bytes()).hexdigest() != version['sha256']:
        raise ApiError(409, 'FILE_CHANGED', '文件与入库版本不一致，请检查存储。')
    cache = conn.execute('SELECT parsed_json,parser_key FROM material_versions WHERE id=?', (version_id,)).fetchone()
    if cache['parsed_json'] and cache['parser_key'] == 'desktop-b:v1':
        return json.loads(cache['parsed_json'])
    try:
        document = parse_document(path)
        validate_document(document)
    except MaterialError as error:
        raise ApiError(422, error.code, str(error)) from error
    result = document.to_dict()
    conn.execute('UPDATE material_versions SET parsed_json=?,parser_key=?,parsed_at=? WHERE id=?',
                 (json.dumps(result, ensure_ascii=False), 'desktop-b:v1', now(), version_id))
    return result


def ui_blocks(document):
    blocks = []
    for block in document['blocks']:
        kind = block['type']
        # B table containers and cell blocks are not duplicated into invented rows.
        if kind not in {'title', 'heading', 'paragraph', 'cell', 'formula', 'image'}:
            continue
        source = block['source']
        item = {'id': block['id'], 'kind': 'heading' if kind in {'title','heading'} else 'image' if kind == 'image' else 'paragraph',
                'text': block['text'] or ('图片对象（结构化定位；不代表原页渲染）' if kind == 'image' else ''),
                'source': source}
        for key in ['page', 'slide', 'paragraph', 'line_start', 'line_end']:
            if source.get(key) is not None:
                item[key] = source[key]
        blocks.append(item)
    return blocks


def material_view(conn, settings, material_id):
    material = material_row(conn, material_id)
    versions = list(conn.execute(materials.VERSION_QUERY + ' WHERE v.material_id=? ORDER BY v.version_no', (material_id,)))
    if not versions:
        raise ApiError(409, 'VERSION_NOT_FOUND', '材料没有可读版本。')
    documents = [(version, parsed(conn, settings, version['version_id'])) for version in versions]
    first, latest = versions[0], versions[-1]
    return {'id': material_id, 'projectId': material['project_id'], 'name': material['name'],
            'kind': Path(first['original_name']).suffix.lower()[1:], 'createdAt': material['created_at'],
            'blocks': ui_blocks(documents[0][1]),
            'revisions': [{'id': version['version_id'], 'name': f"编辑版本 {version['version_no']-1}", 'createdAt': version['created_at'], 'blocks': ui_blocks(doc)} for version, doc in documents[1:]],
            'versionId': latest['version_id'], 'originalVersionId': first['version_id'],
            'rawText': documents[-1][1].get('raw_text'), 'warnings': documents[-1][1]['warnings'],
            'previewState': 'ready', 'demo': False}


def task_row(conn, task_id):
    row = conn.execute('SELECT * FROM desktop_tasks WHERE id=?', (task_id,)).fetchone()
    if row is None:
        raise ApiError(404, 'TASK_NOT_FOUND', '评审任务不存在。')
    return row


def task_view(conn, task_id):
    row = task_row(conn, task_id)
    result = json.loads(row['result_json']) if row['result_json'] else None
    decisions = json.loads(row['decisions_json'])
    snapshot = TaskInput.model_validate_json(row['snapshot_json'])
    blocks = {block['id']: block for block in snapshot.document['blocks']}
    issues = []
    for issue in result['issues'] if result else []:
        source = issue['location']['source']
        entry = {'id': issue['id'], 'location': {'blockId': issue['location']['block_id'], **{key: source[key] for key in ['page','slide','paragraph','line_start','line_end'] if source.get(key) is not None}},
                 'title': issue['criterion_name'], 'severity': issue['severity'], 'category': issue['criterion'],
                 'evidence': issue['evidence']['quote'] or '已确认图片证据', 'standard': issue['review_standard'],
                 'original': blocks[issue['location']['block_id']]['text'], 'suggestion': issue['suggestion'],
                 'decision': 'pending', 'suggestionKind': 'advice'}
        entry.update(decisions.get(issue['id'], {}))
        issues.append(entry)
    seq = conn.execute('SELECT coalesce(max(seq),0) FROM desktop_events WHERE task_id=?', (task_id,)).fetchone()[0]
    steps=[{'seq':s['seq'],'action':s['action'],'status':s['status'],'label':s['label'],
            'observation':json.loads(s['observation_json']) if s['observation_json'] else None,
            'createdAt':s['created_at']} for s in conn.execute('SELECT * FROM agent_steps WHERE task_id=? ORDER BY seq',(task_id,))]
    return {'id': task_id, 'materialId': row['material_id'], 'profile': row['profile'], 'status': row['status'],
            'progress': 100 if row['status'] == 'completed' else 0, 'progressKnown': row['status'] == 'completed',
            'eventId': seq, 'issues': issues, 'error': row['error'], 'createdAt': row['created_at'],
            'versionId': row['version_id'], 'provider': row['provider'], 'result': result,
            'agent': {'mode':row['execution_mode'],'goal':row['goal'],'parentTaskId':row['parent_task_id'],
                      'answer':row['agent_answer'],'termination':row['termination'],'steps':steps}}


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Name(Contract):
    name: str = Field(min_length=1, max_length=160)


@router.get('/projects')
def projects(conn=Depends(get_db)):
    return [{'id': row['id'], 'name': row['name'], 'updatedAt': row['updated_at']} for row in conn.execute('SELECT * FROM projects WHERE archived=0 ORDER BY created_at DESC')]


@router.post('/projects')
def create_project(body: Name, request: Request, conn=Depends(get_db)):
    result = materials.create_project(materials.ProjectCreate(name=body.name), request, conn)
    return {'id': result['id'], 'name': result['name'], 'updatedAt': result['updated_at']}


@router.patch('/projects/{project_id}')
def rename_project(project_id: str, body: Name, conn=Depends(get_db)):
    if not body.name.strip():
        raise ApiError(422, 'INVALID_NAME', '名称不能为空。')
    materials.project_record(conn, project_id)
    with transaction(conn):
        conn.execute('UPDATE projects SET name=?,updated_at=? WHERE id=?', (body.name.strip(), now(), project_id))
    return {'ok': True}


@router.delete('/projects/{project_id}')
def archive_project(project_id: str, conn=Depends(get_db)):
    materials.project_record(conn, project_id)
    with transaction(conn):
        if conn.execute("SELECT 1 FROM desktop_tasks t JOIN materials m ON m.id=t.material_id WHERE m.project_id=? AND t.status IN ('queued','running','cancelling')", (project_id,)).fetchone():
            raise ApiError(409, 'TASK_ACTIVE', '请先取消项目中正在执行的任务。')
        conn.execute('UPDATE projects SET archived=1,updated_at=? WHERE id=?', (now(), project_id))
    return {'ok': True, 'retained': '原文件和历史记录保留于本地数据目录。'}


@router.get('/projects/{project_id}/materials')
def list_materials(project_id: str, request: Request, conn=Depends(get_db)):
    rows = conn.execute('SELECT id FROM materials WHERE project_id=? AND archived=0 ORDER BY created_at', (project_id,)).fetchall()
    result = []
    for row in rows:
        try:
            result.append(material_view(conn, request.app.state.settings, row['id']))
        except ApiError as error:
            material = material_row(conn, row['id'])
            latest = conn.execute(materials.VERSION_QUERY + ' WHERE v.material_id=? ORDER BY v.version_no DESC LIMIT 1', (row['id'],)).fetchone()
            result.append({'id': row['id'], 'projectId': project_id, 'name': material['name'],
                           'kind': Path(latest['original_name']).suffix.lower()[1:], 'createdAt': material['created_at'],
                           'blocks': [], 'revisions': [], 'versionId': latest['version_id'], 'previewState': 'awaiting-parser',
                           'demo': False, 'parseError': error.message})
    return result


@router.post('/projects/{project_id}/materials')
def upload(project_id: str, request: Request, file: UploadFile, conn=Depends(get_db)):
    project = materials.project_record(conn, project_id)
    if project['archived']:
        raise ApiError(409, 'PROJECT_ARCHIVED', '项目已移除。')
    result = materials.import_material(project_id, request, conn, file)
    try:
        return material_view(conn, request.app.state.settings, result['material_id'])
    except ApiError as error:
        # The original upload is retained; do not create an invisible duplicate on retry.
        return {'id': result['material_id'], 'projectId': project_id, 'name': result['original_name'],
                'kind': Path(result['original_name']).suffix.lower()[1:], 'createdAt': result['created_at'],
                'blocks': [], 'revisions': [], 'versionId': result['version_id'], 'previewState': 'awaiting-parser',
                'demo': False, 'parseError': error.message}


@router.delete('/materials/{material_id}')
def archive_material(material_id: str, conn=Depends(get_db)):
    material_row(conn, material_id)
    with transaction(conn):
        if conn.execute("SELECT 1 FROM desktop_tasks WHERE material_id=? AND status IN ('queued','running','cancelling')", (material_id,)).fetchone():
            raise ApiError(409, 'TASK_ACTIVE', '请先取消材料中正在执行的任务。')
        conn.execute('UPDATE materials SET archived=1,updated_at=? WHERE id=?', (now(), material_id))
    return {'ok': True}


class BlocksInput(Contract):
    blocks: list[dict] = Field(max_length=10000)
    sourceVersionId: str
    rawText: str | None = Field(default=None, max_length=900000)


@router.post('/materials/{material_id}/revisions')
def save_text(material_id: str, body: BlocksInput, request: Request, conn=Depends(get_db)):
    material = material_row(conn, material_id)
    source = version_row(conn, body.sourceVersionId)
    extension = Path(source['original_name']).suffix.lower()
    if source['material_id'] != material_id or extension not in {'.txt', '.md'}:
        raise ApiError(415, 'UNSUPPORTED_EDIT', '直接编辑仅支持该材料的 TXT/Markdown；Office 修改请上传新版本。')
    if any(not isinstance(block.get('text'), str) for block in body.blocks):
        raise ApiError(422, 'INVALID_BLOCK', '正文内容无效。')
    content = (body.rawText if body.rawText is not None else '\n\n'.join(block['text'] for block in body.blocks)).encode('utf-8')
    file = UploadFile(filename=source['original_name'], file=io.BytesIO(content))
    materials.add_version(material_id, request, conn, file, body.sourceVersionId)
    return material_view(conn, request.app.state.settings, material['id'])


class PreviewInput(Contract):
    materialId: str
    profile: Literal['paper','proposal','slides']
    provider: Literal['mock','deepseek'] = 'mock'
    blockIds: list[str] | None = Field(default=None, max_length=512)
    executionMode: Literal['pipeline','agent'] = 'pipeline'
    goal: str = Field(default='', max_length=1200)
    parentTaskId: str | None = None


def intent_digest(task, goal, context, provider, mode):
    # Consent binds objective and prior context as well as exact selected text.
    scope_digest = preview_scope(task).text_digest
    return hashlib.sha256(json.dumps([scope_digest,goal,context,provider,mode],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


@router.post('/scope')
def scope(body: PreviewInput, request: Request, conn=Depends(get_db)):
    material_row(conn, body.materialId)
    latest = conn.execute(materials.VERSION_QUERY + ' WHERE v.material_id=? ORDER BY v.version_no DESC LIMIT 1', (body.materialId,)).fetchone()
    document = parsed(conn, request.app.state.settings, latest['version_id'])
    profile_id = PROFILES[body.profile]
    context = ''
    if body.executionMode=='agent' and not body.goal.strip():
        raise ApiError(422,'GOAL_REQUIRED','请输入智能体本次要完成的目标。')
    if body.parentTaskId:
        parent=task_row(conn,body.parentTaskId)
        if parent['material_id']!=body.materialId or parent['execution_mode']!='agent':
            raise ApiError(409,'CONTEXT_CONFLICT','继续任务必须属于当前材料的智能体记录。')
        if parent['status'] not in {'completed','failed','cancelled'}:
            raise ApiError(409,'TASK_ACTIVE','请先等待或取消上一轮。')
        # Carry only public goal/answer, not full documents or hidden reasoning.
        # Generated summaries may quote text: show the COMPLETE context for new consent.
        context=json.dumps({'previous_goal':parent['goal'],'previous_answer':parent['agent_answer'],
                            'previous_status':parent['status'],'same_version':parent['version_id']==latest['version_id']},ensure_ascii=False)
    try:
        select_skill(load_profile(profile_id), document['format'])
        allowed = [block for block in document['blocks'] if block['type'] in ALLOWED_TEXT and block['text'].strip()]
        selected = allowed if body.blockIds is None else [block for block in allowed if block['id'] in body.blockIds]
        if body.blockIds is not None and set(body.blockIds) != {block['id'] for block in selected}:
            raise ApiError(422, 'INVALID_SCOPE', '选择包含无法发送的内容块。')
        task_id = new_id()
        task = TaskInput(task_id=task_id, revision_id=latest['version_id'], profile_id=profile_id, document=document,
                         selection=Selection(text=[TextSlice(block_id=block['id']) for block in selected]))
        preview = preview_scope(task)
    except (ReviewError, ValueError) as error:
        raise ApiError(422, 'SCOPE_INVALID', str(error)) from error
    timestamp = now()
    bound_digest=intent_digest(task,body.goal.strip(),context,body.provider,body.executionMode)
    with transaction(conn):
        conn.execute('INSERT INTO desktop_tasks(id,material_id,version_id,profile,provider,status,snapshot_json,created_at,updated_at,execution_mode,goal,parent_task_id,intent_digest,agent_context) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (task_id, body.materialId, latest['version_id'], body.profile, body.provider, 'awaiting_confirmation', task.model_dump_json(), timestamp, timestamp,
                      body.executionMode,body.goal.strip(),body.parentTaskId,bound_digest,context))
    # This record does not enter the queue, and may never trigger a model request until confirmed.
    return {'taskId': task_id, 'versionId': latest['version_id'], 'provider': body.provider,
            'destination': '仅本机 · C Mock（不联网，不产生真实评审）' if body.provider == 'mock' else 'https://api.deepseek.com/chat/completions · deepseek-flash',
            'textDigest': preview.text_digest, 'intentDigest':bound_digest,'goal':body.goal.strip(),'context':context,
            'executionMode':body.executionMode,'text': [span.model_dump(mode='json') for span in preview.text],
            'images': [], 'note': '仅授权下方文字、任务目标及显示的上一轮摘要。智能体可在最多8次决策、2轮内容评审内，将这些内容和本地工具观察发送至所选模型；单轮总时限240秒。只读白名单工具，不执行命令、不改原文件、不浏览外部网址。离线模式不联网。'}


class ConfirmInput(Contract):
    textDigest: str = Field(pattern='^[0-9a-f]{64}$')
    confirmed: Literal[True]
    intentDigest: str | None = Field(default=None,pattern='^[0-9a-f]{64}$')


@router.post('/tasks/{task_id}/confirm')
def confirm(task_id: str, body: ConfirmInput, request: Request, conn=Depends(get_db)):
    import hmac
    with transaction(conn):
        row = task_row(conn, task_id)
        material_row(conn, row['material_id'])
        if row['status'] != 'awaiting_confirmation':
            raise ApiError(409, 'TASK_STATE', '该范围已提交，请勿重复确认。')
        latest = conn.execute('SELECT id FROM material_versions WHERE material_id=? ORDER BY version_no DESC LIMIT 1', (row['material_id'],)).fetchone()[0]
        if latest != row['version_id']:
            raise ApiError(409, 'VERSION_CONFLICT', '材料已有新版本，请重新预览确认。')
        current = parsed(conn, request.app.state.settings, row['version_id'])
        task = TaskInput.model_validate_json(row['snapshot_json'])
        if current != task.document:
            raise ApiError(409, 'SCOPE_CHANGED', '原文解析已变化，请重新预览。')
        preview = preview_scope(task)
        if row['execution_mode']=='agent':
            expected=intent_digest(task,row['goal'],row['agent_context'],row['provider'],row['execution_mode'])
            if not body.intentDigest or not hmac.compare_digest(body.intentDigest,expected) or row['intent_digest']!=expected:
                raise ApiError(409,'INTENT_CHANGED','任务目标或历史摘要的确认已失效，请重新预览。')
        if not hmac.compare_digest(body.textDigest, preview.text_digest):
            raise ApiError(409, 'SCOPE_CHANGED', '确认摘要与当前选段不一致。')
        task = task.model_copy(update={'approval': Approval(text_digest=preview.text_digest)})
        conn.execute('UPDATE desktop_tasks SET snapshot_json=? WHERE id=?', (task.model_dump_json(), task_id))
        change(conn, task_id, 'queued')
    request.app.state.desktop_engine.submit(task_id)
    return task_view(conn, task_id)


@router.get('/materials/{material_id}/tasks')
def tasks(material_id: str, conn=Depends(get_db)):
    material_row(conn, material_id)
    ids = conn.execute("SELECT id FROM desktop_tasks WHERE material_id=? AND status<>'awaiting_confirmation' ORDER BY created_at DESC", (material_id,)).fetchall()
    return [task_view(conn, row['id']) for row in ids]


@router.get('/tasks/{task_id}')
def get_task(task_id: str, conn=Depends(get_db)):
    return task_view(conn, task_id)


@router.post('/tasks/{task_id}/cancel')
def cancel(task_id: str, request: Request, conn=Depends(get_db)):
    with transaction(conn):
        row = task_row(conn, task_id)
        if row['status'] not in {'queued','running'}:
            raise ApiError(409, 'TASK_STATE', '任务已结束或正在取消。')
        change(conn, task_id, 'cancelled' if row['status'] == 'queued' else 'cancelling')
    request.app.state.desktop_engine.cancel(task_id)
    return task_view(conn, task_id)


class DecisionInput(Contract):
    decision: Literal['pending','accepted','rejected','edited']
    editedText: str | None = Field(default=None, max_length=20000)


@router.patch('/tasks/{task_id}/issues/{issue_id}')
def decide(task_id: str, issue_id: str, body: DecisionInput, conn=Depends(get_db)):
    with transaction(conn):
        row = task_row(conn, task_id)
        if row['status'] != 'completed':
            raise ApiError(409, 'TASK_STATE', '任务完成后才能处理建议。')
        result = json.loads(row['result_json'])
        if issue_id not in {issue['id'] for issue in result['issues']}:
            raise ApiError(404, 'ISSUE_NOT_FOUND', '建议不存在。')
        if body.decision == 'edited' and not (body.editedText or '').strip():
            raise ApiError(422, 'EMPTY_EDIT', '请输入明确的修改后正文。')
        decisions = json.loads(row['decisions_json'])
        decisions[issue_id] = body.model_dump(exclude_none=True)
        conn.execute('UPDATE desktop_tasks SET decisions_json=?,updated_at=? WHERE id=?', (json.dumps(decisions, ensure_ascii=False), now(), task_id))
        append_event(conn, task_id, row['status'])
    return task_view(conn, task_id)


@router.get('/tasks/{task_id}/events')
def events(task_id: str, after: int = 0, conn=Depends(get_db)):
    task_row(conn, task_id)
    rows = [dict(row) for row in conn.execute('SELECT seq,status,created_at FROM desktop_events WHERE task_id=? AND seq>? ORDER BY seq LIMIT 500', (task_id, max(0, after)))]
    return {'items': rows, 'next_after': rows[-1]['seq'] if rows else after}


@router.websocket('/tasks/{task_id}/events/ws')
async def watch(websocket: WebSocket, task_id: str, after: int = 0):
    await websocket.accept()
    db_path = websocket.app.state.settings.db_path
    def read(cursor):
        with session(db_path) as conn:
            return events(task_id, cursor, conn)
    receiver = asyncio.create_task(websocket.receive())
    try:
        while True:
            page = await run_in_threadpool(read, after)
            for event in page['items']:
                await websocket.send_json(event)
                after = event['seq']
            done, _ = await asyncio.wait({receiver}, timeout=0.25)
            if done:
                message = receiver.result()
                if message['type'] == 'websocket.disconnect':
                    break
                receiver = asyncio.create_task(websocket.receive())
    except (WebSocketDisconnect, RuntimeError):
        pass
    except ApiError:
        await websocket.close(code=4404)
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)


class ExportInput(Contract):
    taskId: str | None = None
    revisionId: str | None = None
    format: Literal['text','report']


@router.post('/materials/{material_id}/exports')
def export(material_id: str, body: ExportInput, request: Request, conn=Depends(get_db)):
    material = material_row(conn, material_id)
    task = task_view(conn, body.taskId) if body.taskId else None
    if task and task['materialId'] != material_id:
        raise ApiError(409, 'TASK_MISMATCH', '任务不属于此材料。')
    stem = Path(material['name']).stem
    if body.format == 'report':
        content = json.dumps({'task': task, 'note': 'provider=mock 为离线固定样例，不是真实模型评审。原件未修改。'}, ensure_ascii=False, indent=2).encode('utf-8')
        name = f'{stem}-评审记录.json'
    else:
        latest = conn.execute(materials.VERSION_QUERY + ' WHERE v.material_id=? ORDER BY v.version_no DESC LIMIT 1', (material_id,)).fetchone()
        if body.revisionId and body.revisionId != latest['version_id']:
            raise ApiError(409, 'VERSION_CONFLICT', '版本已变化，请重新加载。')
        extension = Path(latest['original_name']).suffix.lower()
        if extension not in {'.txt', '.md'}:
            raise ApiError(415, 'UNSUPPORTED_EXPORT', 'Office/PDF 不能用评审意见自动替换正文。请下载版本原件或导出评审记录。')
        document = parsed(conn, request.app.state.settings, latest['version_id'])
        content = (document.get('raw_text') or '').encode('utf-8')
        name = f'{stem}-修改稿{extension}'
    return {'name': name, 'contentBase64': base64.b64encode(content).decode('ascii')}


@router.get('/versions/{version_id}/download')
def download(version_id: str, request: Request, conn=Depends(get_db)):
    return materials.export_version(version_id, request, conn)


def credential_store() -> SystemCredentialStore:
    """独立的依赖项，测试可覆盖，避免真实读写系统钥匙串。"""
    return SystemCredentialStore()


class CredentialPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    apiKey: str = Field(min_length=8, max_length=300)


@router.get('/settings/credential')
def credential_status(store: SystemCredentialStore = Depends(credential_store)):
    """只返回是否已配置，永不返回密钥本身。"""
    try:
        store.read()
        return {'provider': 'deepseek', 'configured': True, 'storage': 'os_keychain'}
    except ReviewError as error:
        if error.code == 'credential_missing':
            return {'provider': 'deepseek', 'configured': False, 'storage': 'os_keychain'}
        raise ApiError(503, error.code, str(error)) from error


@router.put('/settings/credential')
def save_credential(payload: CredentialPayload, store: SystemCredentialStore = Depends(credential_store)):
    """保存 DeepSeek Key。只写系统钥匙串，不落数据库、不写日志。"""
    try:
        store.write(payload.apiKey.strip())
    except ReviewError as error:
        raise ApiError(422, error.code, str(error)) from error
    return {'provider': 'deepseek', 'configured': True, 'storage': 'os_keychain'}


@router.delete('/settings/credential')
def clear_credential(store: SystemCredentialStore = Depends(credential_store)):
    store.delete()
    return {'provider': 'deepseek', 'configured': False, 'storage': 'os_keychain'}


@router.get('/service')
def service_info():
    return {'mode': 'integrated', 'providers': ['mock','deepseek'], 'model': 'deepseek-flash', 'imagesEnabled': False,
            'maxFileBytes': 30*1024*1024, 'credentials': '仅系统凭据管理器，不通过 HTTP 返回密钥。'}


@router.get('/materials/{material_id}/format')
def format_report(material_id: str, request: Request, profile: Literal['paper','proposal','slides']='paper', conn=Depends(get_db)):
    material_row(conn, material_id)
    latest = conn.execute('SELECT id FROM material_versions WHERE material_id=? ORDER BY version_no DESC LIMIT 1', (material_id,)).fetchone()[0]
    shaped = parsed(conn, request.app.state.settings, latest)
    document = Document(format=shaped['format'], filename=shaped['filename'], title=shaped['title'],
                        blocks=[Block(id=b['id'], type=b['type'], source=Source(**b['source']), text=b['text'], level=b['level'], parent_id=b['parent_id'], attrs=b['attrs']) for b in shaped['blocks']],
                        metadata=shaped['metadata'], warnings=shaped['warnings'], raw_text=shaped.get('raw_text'))
    return {'versionId': latest, 'report': check_document(document, PROFILES[profile])}
