import {useState} from 'react';
import {ArrowDownToLine,Terminal,Info,Loader2,ExternalLink} from 'lucide-react';
import {api} from './api';

type Row=Record<string,any>;
export function DownloadPage({user,pub,say}:{user:Row;pub:Row;say:(s:string)=>void}) {
  const [busy,setBusy]=useState(false),[claude,setClaude]=useState(true),[harness,setHarness]=useState(false);
  const hasKey=user.key?.status==='assigned';
  async function download() {
    setBusy(true);
    try {
      const clients=[...(claude?['claude-code']:[]),...(harness?['deepseek-harness']:[])];
      const blob=await api<Blob>('/installer/package','POST',{clients}),url=URL.createObjectURL(blob);
      const link=document.createElement('a');link.href=url;link.download='CampusAI-Setup.zip';
      document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
      say(hasKey?'下载已开始，请在30分钟内启动助手领取配置':'下载已开始，可先安装软件；分配 Key 后重新下载完成模型配置');
    } catch(e) {say((e as Error).message)} finally {setBusy(false)}
  }
  return <>
    <section className="download-feature">
      <div className="download-symbol"><Terminal size={46}/></div>
      <span className="eyebrow">SET UP ONCE. BUILD EVERY DAY.</span>
      <h2>选择你的 AI 编程工具</h2>
      <p>下载带窗口的 Windows 安装助手，<br/>安装 Claude Code、DeepSeek Harness，或同时安装两者。</p>
      <fieldset className="installer-options" disabled={busy}>
        <legend>要安装哪些工具？可同时勾选</legend>
        <label className={claude?'selected':''}><input type="checkbox" checked={claude} onChange={e=>setClaude(e.target.checked)}/><span><strong>Claude Code</strong><small>终端编程助手，配套 CC Switch</small></span></label>
        <label className={harness?'selected':''}><input type="checkbox" checked={harness} onChange={e=>setHarness(e.target.checked)}/><span><strong>DeepSeek Harness</strong><small>DeepSeek 官方工具，本机网页界面</small></span></label>
      </fieldset>
      <button className="primary" disabled={busy||(!claude&&!harness)||pub.key_delivery_enabled!==true||user.status!=='active'} onClick={download}>
        {busy?<Loader2 size={18} className="spin"/>:<ArrowDownToLine size={18}/>}下载我的 Windows 安装助手
      </button>
      <small>Windows 10 / 11 · 解压后双击 Start.cmd · 窗口中可再次调整选项</small>
      {!claude&&!harness&&<p role="status">请至少勾选一个工具。</p>}
    </section>
    {pub.key_delivery_enabled!==true&&<div className="notice"><Info size={17}/><div>请通过可信 HTTPS 地址登录后下载。</div></div>}
    {!hasKey&&<div className="notice"><Info size={17}/><div>当前账户尚未分配 Key，仍可下载并安装软件。{user.role==='admin'?'要自动配置模型，请用已分配 Key 的成员账户登录后下载。':'模型自动配置将在分配 Key 后完成；请届时重新下载。管理员可在「官方 Key 号池」为成员账户指定分配。'}</div></div>}
    <div className="two-columns">
      <section className="panel"><div className="panel-head"><h2>开始使用</h2></div><ol className="readable-list"><li>勾选 Claude Code、DeepSeek Harness，或同时勾选两者。</li><li>下载 ZIP 并完整解压，双击 Start.cmd。</li><li>确认窗口中的选项，点击「开始安装」。</li><li>完成后点击对应的打开按钮，或使用桌面快捷方式。</li></ol></section>
      <section className="panel"><div className="panel-head"><h2>已有环境也可以使用</h2></div><ul className="readable-list"><li>Git 和 Node.js 按需复用或安装。</li><li>未勾选的工具不安装、不修改配置。</li><li>Claude Code 写配置前备份，CC Switch 保留已有供应商。</li><li>Harness 使用学院助手的独立本机环境，保留原有安装。</li></ul></section>
    </div>
    <div className="notice"><Info size={17}/><div>有 Key 时，配置票据单次使用、30 分钟有效。密钥仅领取到你的电脑，模型流量直接连接 DeepSeek。不要分享带票据的安装包或本机配置。</div></div>
    <p><a href="https://github.com/deepseek-ai/deepseek-harness" target="_blank" rel="noreferrer">DeepSeek Harness 官方项目 <ExternalLink size={12}/></a></p>
  </>;
}
