// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../src/App';
import { mock } from '../src/services';
import { seedMaterials, sampleIssues } from '../src/services/fixtures';

beforeEach(() => {
  mock.projects = [{ id: 'p1', name: '城市公共空间研究', updatedAt: new Date().toISOString() }];
  mock.materials = seedMaterials(); mock.failure = false; mock.disconnected = false;
  mock.tasks = [{ id: 't1', materialId: 'm1', profile: 'paper', status: 'completed', progress: 100, eventId: 1, createdAt: new Date().toISOString(), issues: sampleIssues(mock.materials[0]) }];
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
async function ready() {
  render(<App/>);
  await screen.findByText('结论范围超出已有证据');
}
describe('interactive workspace', () => {
  it('uses the unified 问赛 brand', async () => {
    await ready();
    expect(screen.getByRole('link', { name: /问赛/ }).textContent).toBe('问赛WENSAI');
    expect(screen.queryByText('阅序')).toBeNull();
  });
  it('accepts, rejects and manually edits a suggestion, then locates its block', async () => {
    const user = userEvent.setup(); await ready();
    await user.click(screen.getByText('结论范围超出已有证据'));
    expect(document.getElementById('block-b4')?.classList.contains('highlight')).toBe(true);
    await user.click(screen.getAllByRole('button', { name: '接受' })[0]);
    await waitFor(() => expect(mock.tasks[0].issues[0].decision).toBe('accepted'));
    await user.click(screen.getAllByRole('button', { name: '拒绝' })[0]);
    await waitFor(() => expect(mock.tasks[0].issues[0].decision).toBe('rejected'));
    await user.click(screen.getAllByRole('button', { name: '手动编辑' })[0]);
    const dialog = screen.getByRole('dialog'); const textarea = within(dialog).getByLabelText('修改后内容');
    await user.clear(textarea); await user.type(textarea, '人工修改的论证范围');
    await user.click(within(dialog).getByRole('button', { name: '保存' }));
    await waitFor(() => expect(mock.tasks[0].issues[0].editedText).toBe('人工修改的论证范围'));
    expect(mock.materials[0].blocks[3].text).toContain('所有居民');
  });
  it('filters by exact severity and query without inventing severity', async () => {
    const user = userEvent.setup(); await ready();
    await user.selectOptions(screen.getByLabelText('严重程度筛选'), '建议');
    expect(screen.queryByText('结论范围超出已有证据')).toBeNull();
    expect(screen.getByText('研究局限需要更明确')).toBeTruthy();
    await user.type(screen.getByLabelText('搜索评审结果'), '不可能匹配');
    expect(screen.getByText('没有匹配的建议')).toBeTruthy();
  });
  it('requires privacy confirmation before starting and supports cancellation', async () => {
    const user = userEvent.setup(); await ready();
    await user.click(screen.getByRole('button', { name: '开始评审' }));
    const dialog = screen.getByRole('dialog');
    expect((within(dialog).getByRole('button', { name: '开始评审' }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(within(dialog).getByRole('checkbox'));
    await user.click(within(dialog).getByRole('button', { name: '开始评审' }));
    await screen.findByRole('button', { name: '取消任务' });
    await user.click(screen.getByRole('button', { name: '取消任务' }));
    await waitFor(() => expect(mock.tasks[0].status).toBe('cancelled'));
  });
  it('creates, renames and deletes a project with a confirmation dialog', async () => {
    const user = userEvent.setup(); await ready();
    await user.click(screen.getByTitle('创建项目'));
    await user.type(screen.getByLabelText('项目名称'), '测试项目');
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '保存' }));
    await waitFor(() => expect(mock.projects).toHaveLength(2));
    await user.click(screen.getByRole('button', { name: /所有项目/ }));
    await user.click(screen.getByTitle('重命名 测试项目'));
    await user.clear(screen.getByLabelText('项目名称')); await user.type(screen.getByLabelText('项目名称'), '新项目名');
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '保存' }));
    await screen.findByTitle('删除 新项目名'); await user.click(screen.getByTitle('删除 新项目名'));
    expect(mock.projects).toHaveLength(2);
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '确认删除' }));
    await waitFor(() => expect(mock.projects).toHaveLength(1));
  });
  it('imports user PDF honestly as awaiting parser, not example content', async () => {
    await ready(); const file = new File(['%PDF-placeholder'], '用户材料.pdf', { type: 'application/pdf' });
    fireEvent.change(document.querySelector('input[type=file]')!, { target: { files: [file] } });
    await screen.findByText('等待解析服务接入');
    expect(mock.materials.at(-1)?.demo).toBe(false); expect(mock.materials.at(-1)?.blocks).toHaveLength(0);
  });
  it('shows recoverable request errors', async () => {
    const user = userEvent.setup(); await ready(); await user.click(screen.getByRole('button', { name: '设置与隐私' }));
    await user.click(screen.getByLabelText('模拟请求失败（启用后点“重新加载”观察）'));
    await user.click(screen.getByRole('button', { name: '重新加载' }));
    await screen.findByRole('alert');
    await user.click(screen.getByLabelText('模拟请求失败（启用后点“重新加载”观察）'));
    await user.click(within(screen.getByRole('alert')).getByRole('button', { name: '重新加载' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });
  it('asks for a save location before writing an export', async () => {
    const user = userEvent.setup(); await ready(); const write = vi.fn(); const close = vi.fn();
    const picker = vi.fn(async () => ({ name: 'review-report.json', createWritable: async () => ({ write, close }) }));
    Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: picker });
    await user.click(screen.getByRole('button', { name: '导出' }));
    expect(write).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '选择输出路径' }));
    await waitFor(() => expect(close).toHaveBeenCalled()); expect(picker).toHaveBeenCalledOnce(); expect(write).toHaveBeenCalledOnce();
    expect(new TextDecoder().decode(write.mock.calls[0][0])).toContain('"mode": "demo"');
    delete (window as unknown as { showSaveFilePicker?: unknown }).showSaveFilePicker;
  });
});
