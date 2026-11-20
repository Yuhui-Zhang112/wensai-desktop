import { describe, expect, it } from 'vitest';
import { applyIssues, diffTokens, fileKind, locationLabel, MAX_FILE_BYTES, validateFile } from '../src/domain';
import { sampleBlocks, sampleIssues, seedMaterials } from '../src/services/fixtures';
import { normalizeApiBase } from '../src/config';

describe('file selection boundary', () => {
  it('recognizes supported extensions case-insensitively', () => { expect(fileKind('Example.DOCX')).toBe('docx'); expect(fileKind('plan.md')).toBe('md'); });
  it('rejects unsupported, empty and oversized files', () => {
    expect(() => fileKind('a.exe')).toThrow('暂不支持');
    expect(() => validateFile({ name: 'a.txt', size: 0 })).toThrow('为空');
    expect(() => validateFile({ name: 'a.pdf', size: MAX_FILE_BYTES + 1 })).toThrow('30 MB');
  });
});
describe('edits and immutable source', () => {
  it('applies only accepted edits without mutating original', () => {
    const issues = sampleIssues(seedMaterials()[0]); issues[1].decision = 'accepted'; issues[0].decision = 'rejected';
    const result = applyIssues(sampleBlocks, issues);
    expect(result[6].text).toContain('80%'); expect(sampleBlocks[6].text).toContain('90%'); expect(result[3].text).toBe(sampleBlocks[3].text);
  });
  it('honors manual edits', () => { const issues = sampleIssues(seedMaterials()[0]); issues[0].decision = 'edited'; issues[0].editedText = '人工修改'; expect(applyIssues(sampleBlocks, issues)[3].text).toBe('人工修改'); });
  it('prevents silently applying two edits to the same block', () => { const issue = { ...sampleIssues(seedMaterials()[0])[0], decision: 'accepted' as const }; expect(() => applyIssues(sampleBlocks, [issue, { ...issue, id: 'other' }])).toThrow('同一段落'); });
  it('prevents stale version edits', () => { const issue = { ...sampleIssues(seedMaterials()[0])[0], decision: 'accepted' as const, original: 'stale' }; expect(() => applyIssues(sampleBlocks, [issue])).toThrow('原文已变化'); });
  it('does not fabricate findings for uploaded material', () => { expect(sampleIssues({ ...seedMaterials()[0], id: 'user-file', demo: false })).toEqual([]); });
});
describe('diff and locations', () => {
  it('isolates the changed span', () => { expect(diffTokens('有效率90%。', '有效率80%。')).toEqual({ prefix: '有效率', removed: '9', added: '8', suffix: '0%。' }); });
  it.each([['', '新增'], ['删除', ''], ['相同', '相同'], ['a😀x', 'a😎x']])('reconstructs source and target for %s', (a, b) => { const d = diffTokens(a, b); expect(d.prefix + d.removed + d.suffix).toBe(a); expect(d.prefix + d.added + d.suffix).toBe(b); });
  it('shows actual supplied locations', () => { expect(locationLabel({ page: 2, paragraph: 4 })).toBe('第 2 页 · 段落 4'); expect(locationLabel({ slide: 3 })).toBe('幻灯片 3'); });
});
describe('loopback API only', () => {
  it('normalizes local URLs', () => { expect(normalizeApiBase('http://127.0.0.1:8765/')).toBe('http://127.0.0.1:8765'); });
  it.each(['https://evil.example', 'http://192.168.1.1', 'http://localhost.evil.com', 'file:///test', 'http://secret@localhost:80', 'http://localhost?key=secret'])('rejects %s', value => { expect(() => normalizeApiBase(value)).toThrow(); });
});
