import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpService, approvals } from '../src/services/http';
class FakeSocket {
  static instances: FakeSocket[]=[];
  onopen?:()=>void; onclose?:(e:{code:number})=>void; onerror?:()=>void; onmessage?:(e:{data:string})=>void;
  closed=false;
  constructor(public url:URL) { FakeSocket.instances.push(this); }
  close() { this.closed=true; }
  send(seq:number) { this.onmessage?.({data:JSON.stringify({seq})}); }
}
afterEach(()=> {vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers();FakeSocket.instances=[];approvals.clear();});
describe('integrated A/B/C adapter',()=>{
  it('preserves complete editor text and sends the source version',async()=>{
    const raw='# 标题\r\n\r\n\r\n正文  \r\n';
    const fetch=vi.fn(async(_url:string,_init?:RequestInit)=>new Response(JSON.stringify(_url.endsWith('/revisions') ? {id:'m1',versionId:'v2'} : [{id:'m1',versionId:'v1'}])));
    vi.stubGlobal('fetch',fetch);
    const service=new HttpService();await service.listMaterials('p1');
    await service.saveRevision('m1',[{id:'editor',kind:'paragraph',text:raw}]);
    const body=JSON.parse(String(fetch.mock.calls[1][1]?.body));
    expect(body.rawText).toBe(raw);expect(body.sourceVersionId).toBe('v1');
  });
  it('uses actual desktop prefix and server error messages',async()=>{
    const fetch=vi.fn(async(_url:string,_init?:RequestInit)=>new Response(JSON.stringify({error:{message:'没有访问权限'}}),{status:403}));vi.stubGlobal('fetch',fetch);
    await expect(new HttpService().getTask('t1')).rejects.toThrow('没有访问权限');
    expect(fetch.mock.calls[0][0]).toContain('/api/v1/desktop/tasks/t1');
  });
  it('refuses task creation without displayed scope approval',async()=>{
    const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
    await expect(new HttpService().createTask('m1','paper')).rejects.toThrow('选段');expect(fetch).not.toHaveBeenCalled();
  });
  it('consumes explicit scope and confirms bound task digest once',async()=>{
    const fetch=vi.fn(async(_url:string,_init?:RequestInit)=>new Response(JSON.stringify({id:'t1'})));vi.stubGlobal('fetch',fetch);
    approvals.set('m1:paper',{taskId:'t1',versionId:'v1',provider:'mock',destination:'local',textDigest:'a'.repeat(64),text:[],note:''});
    await new HttpService().createTask('m1','paper');expect(approvals.size).toBe(0);
    expect(fetch.mock.calls[0][0]).toContain('/tasks/t1/confirm');
  });
  it('resumes WebSocket sequence and ignores duplicates',async()=>{
    vi.useFakeTimers();vi.stubGlobal('WebSocket',FakeSocket);
    const service=new HttpService();vi.spyOn(service,'getTask').mockResolvedValue({id:'t1',eventId:7} as never);
    vi.spyOn(service,'request').mockResolvedValue({items:[{seq:7}]});
    const event=vi.fn(),state=vi.fn();const stop=service.subscribe('t1',5,event,state);
    const first=FakeSocket.instances[0];expect(first.url.toString()).toContain('after=5');
    first.send(6);first.send(6);await vi.advanceTimersByTimeAsync(0);expect(event).toHaveBeenCalledTimes(1);
    first.onclose?.({code:1006});await vi.advanceTimersByTimeAsync(2000);
    expect(FakeSocket.instances[1].url.toString()).toContain('after=7');
    stop();expect(FakeSocket.instances[1].closed).toBe(true);
    await vi.advanceTimersByTimeAsync(20000);expect(FakeSocket.instances).toHaveLength(2);
  });
});
