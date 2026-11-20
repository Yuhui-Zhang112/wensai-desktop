import { useState } from 'react';
import { Bot, Check, ChevronRight, Compass, CornerDownLeft, LoaderCircle, MessageCircle, ShieldCheck, Wrench } from 'lucide-react';
import type { Task } from './domain';

const names: Record<string,string> = { plan:'决策', inspect_scope:'材料读取',search_standards:'标准检索',check_format:'格式检查',review_content:'内容评审',ask_user:'请求补充',finish:'总结' };
export function AgentConsole({ task, onStart, onContinue, onResults, onCancel, disabled }: {
  task: Task | null; onStart: (goal:string)=>void; onContinue:(goal:string,parentId:string)=>void; onResults:()=>void; onCancel?:()=>void; disabled:boolean;
}) {
  const [goal,setGoal]=useState('按竞赛材料要求检查论证与证据，优先找出最影响可信度的问题，并给出修改顺序。');
  const [reply,setReply]=useState('');
  const agent = task?.agent?.mode==='agent' ? task.agent : null;
  const running=!!task && ['queued','running','cancelling'].includes(task.status);
  return <div className="agent-console review-scroll">
    <div className="agent-intro"><span className="agent-orb"><Bot size={25}/></span><div><h3>让目标驱动下一步</h3><p>我会按任务选择工具，根据观察继续检查，证据不足时向你提问。</p></div></div>
    <label className="field agent-goal">你希望智能体完成什么？<textarea aria-label="智能体任务目标" rows={3} maxLength={1200} value={goal} onChange={e=>setGoal(e.target.value)} placeholder="例如：只查格式；或重点检查方法与预算是否可信"/></label>
    <div className="agent-presets">{['只做格式检查，列出规则发现与无法检查的项。','重点核查方法、数据与结论是否对应，给出修改优先级。','检查计划、预算与资源可行性；缺少赛事要求时向我追问。'].map((value,index)=><button className="agent-chip" key={value} onClick={()=>setGoal(value)}>{['格式巡检','证据审阅','竞赛把关'][index]}<ChevronRight size={12}/></button>)}</div>
    <button className="button primary agent-start" disabled={disabled||running||!goal.trim()} onClick={()=>onStart(goal)}><Compass size={15}/>确认范围并开始任务</button>
    <div className="agent-safety"><ShieldCheck size={14}/><span>只读工具 · 每轮重新授权 · 最多 8 次决策 / 2 轮内容评审<br/>默认离线演示；真实自主选工具需要 DeepSeek。</span></div>
    {agent && task && <section className="agent-run" aria-label="智能体执行记录">
      <div className="row between"><span className="eyebrow">CURRENT MISSION</span><span className={`pill ${task.status}`}>{task.provider==='mock'?'离线策略演示':'模型驱动'} · {running?'执行中':task.status==='completed'?'本轮结束':task.status==='failed'?'失败':'已取消'}</span></div>
      <div className="agent-user-message"><MessageCircle size={14}/><p>{agent.goal}</p></div>
      {running&&onCancel&&<button className="text-button" disabled={disabled||task.status==='cancelling'} onClick={onCancel}>{task.status==='cancelling'?'正在取消…':'停止本轮任务'}</button>}
      <div className="agent-trace-heading"><Wrench size={14}/><strong>工具执行记录</strong><span>公开操作与结果，不展示隐藏思维链</span></div>
      {!agent.steps.length && <p className="small subtle">{running?'正在排队，尚无工具记录。':'本轮尚未执行工具。'}</p>}
      <ol className="agent-trace">{agent.steps.map(step=><li key={step.seq} className={`agent-step ${step.status}`}><span className="agent-step-dot">{step.status==='running'?<LoaderCircle size={13} className="spin"/>:step.status==='completed'?<Check size={12}/>:<span>!</span>}</span><div><div className="row between"><strong>{step.label}</strong><small>{step.status==='running'?'进行中':step.status==='completed'?'完成':step.status==='cancelled'?'已取消':'未完成'}</small></div>{step.action==='plan'&&step.observation?.next_action ? <p className="small subtle">下一步：{names[String(step.observation.next_action)]||String(step.observation.next_action)}</p> : null}{step.observation && step.action!=='plan' && <details><summary>查看工具返回</summary><pre>{JSON.stringify(step.observation,null,2)}</pre></details>}</div></li>)}</ol>
      {agent.answer && <div className="agent-answer"><span className="micro">{agent.termination==='needs_input'?'需要你补充':'本轮结论'}</span><p>{agent.answer}</p><p className="micro">{task.provider==='mock'?'离线固定策略示例，非真实自主决策。':'智能体综合摘要未做逐句证据校验；可核验引文以“评审结果”中的 C 报告为准。'}</p>{task.issues.length>0&&<button className="text-button" onClick={onResults}>查看 {task.issues.length} 条证据化建议<ChevronRight size={14}/></button>}</div>}
      {task.error&&<p role="alert" className="error-text">{task.error}</p>}
      {!running&&<div className="agent-followup"><label className="field">补充信息或提出下一步要求<textarea aria-label="补充智能体任务" rows={2} maxLength={1200} value={reply} onChange={e=>setReply(e.target.value)} placeholder="例如：比赛限时 5 分钟，请重新检查讲述节奏。"/></label><button className="button" disabled={disabled||!reply.trim()} onClick={()=>onContinue(reply,task.id)}><CornerDownLeft size={14}/>重新确认并继续</button><p className="micro">保留本轮记录，创建新一轮；确认页会展示将携带的公开摘要。</p></div>}
    </section>}
    {!agent&&<div className="agent-empty"><div className="agent-capabilities"><span><Wrench size={15}/>选工具</span><span><ShieldCheck size={15}/>查证据</span><span><MessageCircle size={15}/>有疑问追问</span></div><p>从一个明确目标开始。执行记录会出现在这里；文件不会被自动修改。</p></div>}
  </div>;
}
