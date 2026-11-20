// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ScopeApproval } from '../src/ScopeApproval';
import { approvals } from '../src/services/http';
afterEach(()=>{cleanup();vi.unstubAllGlobals();approvals.clear();});
it('requires exact scope approval again after changing provider',async()=>{
  const fetch=vi.fn(async(_url:string,_init?:RequestInit)=>new Response(JSON.stringify({taskId:'t1',versionId:'v1',provider:'mock',destination:'local',textDigest:'a'.repeat(64),text:[{block_id:'b1',text:'实际待评文字',source:{}}],note:'不含图片'})));
  vi.stubGlobal('fetch',fetch);
  const ready=vi.fn(),user=userEvent.setup();
  render(<ScopeApproval materialId="m1" profile="paper" onReady={ready}/>);
  await screen.findByText('实际待评文字');
  expect(approvals.size).toBe(0);
  await user.click(screen.getByRole('checkbox',{name:/我已核对范围/}));
  expect(approvals.has('m1:paper')).toBe(true);
  await user.selectOptions(screen.getByRole('combobox'),'deepseek');
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));
  expect(approvals.size).toBe(0);expect(ready).toHaveBeenLastCalledWith(false);
  expect(JSON.parse(String(fetch.mock.calls[1]?.[1]?.body)).provider).toBe('deepseek');
});
it('disables confirmation until a changed block selection is previewed',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({taskId:'t1',versionId:'v1',provider:'mock',destination:'local',textDigest:'a'.repeat(64),text:[{block_id:'b1',text:'实际待评文字',source:{}}],note:''}))));
  const user=userEvent.setup();
  render(<ScopeApproval materialId="m1" profile="paper" onReady={()=>{}}/>);
  await screen.findByText('实际待评文字');
  await user.click(screen.getByRole('checkbox',{name:/b1 实际待评文字/}));
  expect((screen.getByRole('checkbox',{name:/范围已变化/}) as HTMLInputElement).disabled).toBe(true);
  expect(approvals.size).toBe(0);
});
