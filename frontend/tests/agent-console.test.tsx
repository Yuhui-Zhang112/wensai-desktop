// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {AgentConsole} from '../src/AgentConsole';
import type {Task} from '../src/domain';
afterEach(cleanup);
const task:Task={id:'t1',materialId:'m1',profile:'paper',status:'completed',progress:100,eventId:8,issues:[],createdAt:new Date().toISOString(),provider:'mock',agent:{mode:'agent',goal:'查证据',answer:'请补充独立测量次数。',termination:'needs_input',steps:[{seq:1,action:'inspect_scope',label:'读取授权范围',status:'completed',createdAt:new Date().toISOString(),observation:{selected_blocks:2}}]}};
it('sends the goal for explicit scope approval instead of directly starting tools',async()=>{
  const start=vi.fn(),user=userEvent.setup();
  render(<AgentConsole task={null} disabled={false} onStart={start} onContinue={()=>{}} onResults={()=>{}}/>);
  await user.click(screen.getByRole('button',{name:/格式巡检/}));
  await user.click(screen.getByRole('button',{name:'确认范围并开始任务'}));
  expect(start).toHaveBeenCalledWith('只做格式检查，列出规则发现与无法检查的项。');
});
it('shows tool observations and carries the parent id on a follow-up',async()=>{
  const follow=vi.fn(),user=userEvent.setup();
  render(<AgentConsole task={task} disabled={false} onStart={()=>{}} onContinue={follow} onResults={()=>{}}/>);
  expect(screen.getByText('读取授权范围')).toBeTruthy();
  expect(screen.getByText('请补充独立测量次数。')).toBeTruthy();
  await user.type(screen.getByLabelText('补充智能体任务'),'已测量三次');
  await user.click(screen.getByRole('button',{name:'重新确认并继续'}));
  expect(follow).toHaveBeenCalledWith('已测量三次','t1');
});
it('prevents another run while the current run is active',()=>{
  render(<AgentConsole task={{...task,status:'running'}} disabled={false} onStart={()=>{}} onContinue={()=>{}} onResults={()=>{}}/>);
  expect((screen.getByRole('button',{name:'确认范围并开始任务'}) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByLabelText('补充智能体任务')).toBeNull();
});
