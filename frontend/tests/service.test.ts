import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockService } from '../src/services/mock';
import type { ConnectionState, TaskEvent } from '../src/domain';
describe('mock workflow', () => {
  let service: MockService;
  beforeEach(() => { service = new MockService(); });
  afterEach(() => vi.useRealTimers());
  it('creates, renames and deletes projects without touching fixtures', async () => {
    const project = await service.createProject('我的项目'); await service.renameProject(project.id, '新名字');
    expect(service.projects.find(p => p.id === project.id)?.name).toBe('新名字');
    await service.deleteProject(project.id); expect(service.projects).toHaveLength(1);
  });
  it('completes a task and resumes events after disconnect', async () => {
    vi.useFakeTimers(); const task = await service.createTask('m1', 'paper'); const events: TaskEvent[] = []; const states: ConnectionState[] = [];
    const stop = service.subscribe(task.id, 1, e => events.push(e), state => states.push(state));
    vi.advanceTimersByTime(1800); service.disconnected = true; vi.advanceTimersByTime(1800); expect(states).toContain('reconnecting');
    const cursor = events.at(-1)!.id; service.disconnected = false; vi.advanceTimersByTime(5400);
    expect(events.at(-1)!.task.status).toBe('completed'); expect(events.at(-1)!.id).toBeGreaterThan(cursor); stop();
    const count = events.length; vi.advanceTimersByTime(10000); expect(events).toHaveLength(count);
  });
  it('cancels a task and does not resume execution', async () => {
    vi.useFakeTimers(); const task = await service.createTask('m1', 'paper'); await service.cancelTask(task.id);
    const stop = service.subscribe(task.id, 1, () => {}, () => {}); vi.advanceTimersByTime(9000);
    expect((await service.getTask(task.id)).status).toBe('cancelled'); stop();
  });
  it('stores decisions and exports marked demo report', async () => {
    await service.decide('t1', 'i2', 'accepted'); const task = await service.getTask('t1');
    expect(task.issues[1].decision).toBe('accepted');
    const report = await service.exportFile(service.materials[0], task, 'report'); const data = JSON.parse(new TextDecoder().decode(report.bytes));
    expect(data.mode).toBe('demo'); expect(data.task.issues[1].decision).toBe('accepted');
    await expect(service.exportFile(service.materials[0], task, 'text')).rejects.toThrow('保格式导出');
  });
  it('retains original text across multiple saved revisions', async () => {
    const original = service.materials[1].blocks[0].text;
    await service.saveRevision('m2', [{ id: 'new', kind: 'paragraph', text: '修改一' }]);
    const updated = await service.saveRevision('m2', [{ id: 'new2', kind: 'paragraph', text: '修改二' }]);
    expect(updated.revisions).toHaveLength(2); expect(updated.blocks[0].text).toBe(original);
  });
  it('blocks simulated failures', async () => { service.failure = true; await expect(service.createTask('m1', 'paper')).rejects.toThrow('模拟服务'); });
  it('shows a failed task and supports a new retry task', async () => {
    vi.useFakeTimers(); service.failNextTask = true; const task = await service.createTask('m1', 'paper');
    const stop = service.subscribe(task.id, 1, () => {}, () => {}); vi.advanceTimersByTime(1800);
    expect((await service.getTask(task.id)).status).toBe('failed'); stop();
    const retry = await service.createTask('m1', 'paper'); expect(retry.status).toBe('queued'); expect(retry.id).not.toBe(task.id);
  });
});
