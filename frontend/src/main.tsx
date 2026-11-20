import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';
import './integration.css';
class Boundary extends React.Component<{ children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <main className="fatal"><h1>页面暂时无法显示</h1><p>服务数据可能与当前界面协议不一致。请检查 A/B/C 对接字段后重试。</p><button onClick={() => location.reload()}>重新加载</button></main> : this.props.children; }
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><Boundary><App/></Boundary></React.StrictMode>);
