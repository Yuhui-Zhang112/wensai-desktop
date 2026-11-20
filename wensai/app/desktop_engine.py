"""A-owned durable task gateway for the unmodified C engine.

Keep full nullable C scores and exact evidence. Legacy A reports remain unchanged.
"""
import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from .db import new_id, now, session, transaction
from .review_agent import AgentConfig, DeepSeekProvider, MockProvider, ReviewAgent, ReviewError, TaskInput


def append_event(conn, task_id, status):
    conn.execute('INSERT INTO desktop_events SELECT ?,coalesce(max(seq),0)+1,?,? FROM desktop_events WHERE task_id=?',
                 (task_id, status, now(), task_id))


def change(conn, task_id, status, **values):
    allowed = {'result_json', 'error', 'meta_json'}
    if set(values) - allowed:
        raise ValueError('invalid update')
    fields = ','.join(f'{key}=?' for key in values)
    conn.execute(f'UPDATE desktop_tasks SET status=?,updated_at=?{"," + fields if fields else ""} WHERE id=?',
                 (status, now(), *values.values(), task_id))
    append_event(conn, task_id, status)


class Gateway:
    def __init__(self, engine):
        self.engine = engine
        self.db = engine.settings.db_path

    async def load(self, task_id):
        with session(self.db) as conn:
            row = conn.execute('SELECT snapshot_json FROM desktop_tasks WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise ReviewError('task_not_found', '任务不存在。')
        return TaskInput.model_validate_json(row['snapshot_json'])

    async def claim(self, task, meta):
        with session(self.db) as conn, transaction(conn):
            row = conn.execute('SELECT * FROM desktop_tasks WHERE id=?', (task.task_id,)).fetchone()
            if row['status'] != 'queued' or TaskInput.model_validate_json(row['snapshot_json']) != task:
                return False
            if self.engine.stopping.is_set():
                return False
            change(conn, task.task_id, 'running', meta_json=meta.model_dump_json())
            return True

    async def audit(self, attempt):
        with session(self.db) as conn, transaction(conn):
            row = conn.execute('SELECT status FROM desktop_tasks WHERE id=?', (attempt.task_id,)).fetchone()
            if row['status'] != 'running':
                raise asyncio.CancelledError()
            conn.execute('INSERT INTO desktop_audits VALUES (?,?,?,?)', (new_id(), attempt.task_id, attempt.model_dump_json(), now()))

    async def complete(self, result):
        with session(self.db) as conn, transaction(conn):
            row = conn.execute('SELECT status FROM desktop_tasks WHERE id=?', (result.meta.task_id,)).fetchone()
            if row['status'] == 'cancelling':
                change(conn, result.meta.task_id, 'cancelled')
            elif self.engine.stopping.is_set():
                change(conn, result.meta.task_id, 'failed', error='服务关闭，任务未保存。可重新确认并评审。')
            elif row['status'] == 'running':
                change(conn, result.meta.task_id, 'completed', result_json=result.model_dump_json(), meta_json=result.meta.model_dump_json())
            else:
                raise ReviewError('task_conflict', '任务状态已变化。')

    async def fail(self, failure):
        with session(self.db) as conn, transaction(conn):
            row = conn.execute('SELECT status FROM desktop_tasks WHERE id=?', (failure.meta.task_id,)).fetchone()
            if row['status'] == 'cancelling':
                change(conn, failure.meta.task_id, 'cancelled')
            elif row['status'] == 'running':
                change(conn, failure.meta.task_id, 'failed', error=f'{failure.code}：{failure.message}', meta_json=failure.meta.model_dump_json())


class Engine:
    def __init__(self, settings):
        self.settings = settings
        self.stopping = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='wensai-c')
        self.active = {}
        self.lock = threading.Lock()

    def start(self):
        with session(self.settings.db_path) as conn, transaction(conn):
            rows = conn.execute("SELECT id,status FROM desktop_tasks WHERE status IN ('queued','running','cancelling')").fetchall()
            for row in rows:
                # Never silently repeat an external request after a crash.
                change(conn, row['id'], 'cancelled' if row['status'] == 'cancelling' else 'failed',
                       error='服务曾中断，请重新预览范围并确认后创建评审。')
                conn.execute("UPDATE agent_steps SET status=?,updated_at=? WHERE task_id=? AND status='running'",
                             ('cancelled' if row['status']=='cancelling' else 'failed',now(),row['id']))

    def submit(self, task_id):
        self.executor.submit(self._execute, task_id)

    def _execute(self, task_id):
        try:
            asyncio.run(self._run(task_id))
        except asyncio.CancelledError:
            pass
        except Exception:
            # Do not log source text, provider bodies, credentials or raw unvalidated output.
            with session(self.settings.db_path) as conn, transaction(conn):
                row = conn.execute('SELECT status FROM desktop_tasks WHERE id=?', (task_id,)).fetchone()
                if row and row['status'] in {'queued', 'running', 'cancelling'}:
                    change(conn, task_id, 'cancelled' if row['status'] == 'cancelling' else 'failed', error='本地评审执行失败，请检查配置后重试。')

    async def _run(self, task_id):
        with session(self.settings.db_path) as conn:
            row = conn.execute('SELECT provider,status,execution_mode FROM desktop_tasks WHERE id=?', (task_id,)).fetchone()
        if row is None or row['status'] != 'queued' or self.stopping.is_set():
            return
        config = AgentConfig()
        provider = MockProvider() if row['provider'] == 'mock' else DeepSeekProvider(config)
        if row['execution_mode']=='agent':
            from .agent_runtime import AgentRunner
            runner = AgentRunner(Gateway(self),provider,config)
        else:
            runner = ReviewAgent(Gateway(self), provider, config)
        task = asyncio.create_task(runner.run(task_id))
        with self.lock:
            self.active[task_id] = (asyncio.get_running_loop(), task)
        with session(self.settings.db_path) as conn:
            status = conn.execute('SELECT status FROM desktop_tasks WHERE id=?', (task_id,)).fetchone()[0]
        if status == 'cancelling' or self.stopping.is_set():
            task.cancel()
        try:
            await task
        finally:
            with session(self.settings.db_path) as conn, transaction(conn):
                status = conn.execute('SELECT status FROM desktop_tasks WHERE id=?', (task_id,)).fetchone()[0]
                if status == 'cancelling':
                    change(conn, task_id, 'cancelled')
                conn.execute("UPDATE agent_steps SET status=?,updated_at=? WHERE task_id=? AND status='running'",
                             ('cancelled' if status=='cancelling' else 'failed',now(),task_id))
            with self.lock:
                self.active.pop(task_id, None)

    def cancel(self, task_id):
        with self.lock:
            active = self.active.get(task_id)
            if active:
                active[0].call_soon_threadsafe(active[1].cancel)

    def stop(self):
        self.stopping.set()
        with self.lock:
            for loop, task in self.active.values():
                loop.call_soon_threadsafe(task.cancel)
        self.executor.shutdown(wait=True, cancel_futures=False)
