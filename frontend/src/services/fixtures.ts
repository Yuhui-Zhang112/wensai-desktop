import type { Block, Issue, Material } from '../domain';
const createdAt = '2026-11-16T02:00:00Z';
export const sampleBlocks: Block[] = [
  { id: 'b1', kind: 'heading', page: 1, text: '城市公共空间中的步行体验研究' },
  { id: 'b2', kind: 'paragraph', page: 1, paragraph: 1, text: '摘要：本研究探讨城市公共空间与居民步行体验之间的关系，通过现场观察与问卷调查，分析空间设计对使用行为的影响。' },
  { id: 'b3', kind: 'heading', page: 1, text: '01 研究背景与问题' },
  { id: 'b4', kind: 'paragraph', page: 1, paragraph: 2, text: '近年来，城市公共空间越来越受到广泛关注。很多研究已经证明，好的空间设计可以显著提高所有居民的幸福感。' },
  { id: 'b5', kind: 'paragraph', page: 1, paragraph: 3, text: '本研究以三处社区公共空间为观察对象，记录不同时间段的步行流量、停留行为和空间使用情况。研究希望为社区空间的更新提供参考。' },
  { id: 'b6', kind: 'heading', page: 2, text: '02 研究方法' },
  { id: 'b7', kind: 'paragraph', page: 2, paragraph: 4, text: '本次调查共发放问卷120份，收回有效问卷96份，有效率为90%。调查对象为工作日午间到访的居民。' },
  { id: 'b8', kind: 'table', page: 2, text: '表 1 调查概况', rows: [['指标', '数量'], ['发放问卷', '120 份'], ['有效问卷', '96 份'], ['调查时段', '工作日午间']] },
  { id: 'b9', kind: 'heading', page: 3, text: '03 初步结论' },
  { id: 'b10', kind: 'paragraph', page: 3, paragraph: 5, text: '因此，本研究的结论适用于所有城市公共空间的规划与设计。后续将进一步扩大样本范围，补充不同时段的观察记录。' },
  { id: 'b11', kind: 'image', page: 3, text: '空间观察示意图占位。真实图片资源与定位由 B 的解析接口提供。' },
];
export function seedMaterials(): Material[] {
  return [
    { id: 'm1', projectId: 'p1', name: '城市公共空间步行体验研究.docx', kind: 'docx', createdAt, blocks: sampleBlocks, revisions: [], previewState: 'ready', demo: true },
    { id: 'm2', projectId: 'p1', name: '研究计划与时间安排.md', kind: 'md', createdAt, blocks: [
      { id: 'plan1', kind: 'heading', text: '# 研究计划' },
      { id: 'plan2', kind: 'paragraph', paragraph: 1, text: '本研究拟在三个社区展开观察与访谈。先进行预调查，再完善问卷并开展正式研究。' },
    ], revisions: [], previewState: 'ready', demo: true },
    { id: 'm3', projectId: 'p1', name: '开题汇报演示.pptx', kind: 'pptx', createdAt, blocks: [
      { id: 's1', kind: 'heading', slide: 1, text: '城市公共空间步行体验研究' },
      { id: 's2', kind: 'paragraph', slide: 1, text: '研究问题 · 方法设计 · 预期成果' },
      { id: 's3', kind: 'heading', slide: 2, text: '研究方法与样本' },
      { id: 's4', kind: 'paragraph', slide: 2, text: '通过现场观察与问卷收集步行体验数据。样本来自三个社区工作日午间的到访居民。' },
    ], revisions: [], previewState: 'ready', demo: true },
    { id: 'm4', projectId: 'p1', name: '参考阅读材料.pdf', kind: 'pdf', createdAt, blocks: [
      { id: 'pdf1', kind: 'heading', page: 1, text: '公共空间研究参考材料' },
      { id: 'pdf2', kind: 'paragraph', page: 1, paragraph: 1, text: '阅读模式示例。真实 PDF 的文本、页面渲染资源和定位信息需 B 的解析服务提供。PDF 不提供直接修改。' },
    ], revisions: [], previewState: 'ready', demo: true },
  ];
}
export function sampleIssues(material: Material): Issue[] {
  const base = { decision: 'pending' as const, category: '论证与表达' };
  if (material.id === 'm1') return [
    { ...base, id: 'i1', title: '结论范围超出已有证据', severity: '重要', location: { blockId: 'b4', page: 1, paragraph: 2 }, evidence: '“所有居民的幸福感”是全称判断，当前段落未给出研究来源。', standard: '示例标准：概括性结论应提供可核验来源，并说明适用范围。', original: sampleBlocks[3].text, suggestion: '近年来，城市公共空间的使用体验受到关注。既有研究提示，空间设计可能影响居民的活动体验，但其作用仍需结合具体人群与场景加以验证。' },
    { ...base, id: 'i2', title: '问卷有效率与样本数量不一致', severity: '重要', category: '数据一致性', location: { blockId: 'b7', page: 2, paragraph: 4 }, evidence: '有效问卷 96 份，发放 120 份，96 ÷ 120 = 80%，不是 90%。', standard: '示例标准：比例应与原始数量保持一致。', original: sampleBlocks[6].text, suggestion: '本次调查共发放问卷120份，收回有效问卷96份，有效率为80%。调查对象为工作日午间到访的居民。' },
    { ...base, id: 'i3', title: '研究局限需要更明确', severity: '建议', location: { blockId: 'b10', page: 3, paragraph: 5 }, evidence: '样本仅来自三个社区的工作日午间，尚不能推广至所有城市公共空间。', standard: '示例标准：结论应与样本覆盖范围一致。', original: sampleBlocks[9].text, suggestion: '本研究的初步发现可为类似社区公共空间的更新提供参考。受样本与调查时段限制，后续需扩大样本范围，并补充不同时段的观察记录。' },
  ];
  // No generated conclusions for user uploads. Fixtures are only for known demo materials.
  return [];
}
