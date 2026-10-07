import {useEffect, useState} from 'react';
import {Clipboard, Plus, UserPlus} from 'lucide-react';
import {api} from './api';

type Row = Record<string, any>;
export function MemberInvites({active, say, copy}: {active: boolean; say: (s: string) => void; copy: (s: string) => Promise<void>}) {
  const [data, setData] = useState<Row>({items: [], remaining: 0, limit: 5}), [busy, setBusy] = useState(false), [created, setCreated] = useState<Row | null>(null), [error, setError] = useState('');
  const load = async () => {setData(await api('/invites')); setError('');};
  useEffect(() => {load().catch(e => setError(e.message));}, []);
  const date = (value: number) => new Date(value * 1000).toLocaleString('zh-CN', {hour12: false});
  const expired = (row: Row) => row.expires_at && row.expires_at <= Date.now() / 1000;
  async function create() {setBusy(true); try {setCreated(await api('/invites', 'POST')); await load(); say('单人邀请码已生成，请保存后分享给熟人');} catch (e) {say((e as Error).message);} finally {setBusy(false);}}
  async function disable(id: number) {setBusy(true); try {await api(`/invites/${id}/disable`, 'POST'); if (created?.id === id) setCreated(null); await load(); say('邀请码已停用');} catch (e) {say((e as Error).message);} finally {setBusy(false);}}
  return <><section className="panel"><div className="panel-head"><div><h2>邀请好友</h2><p>邀请熟人加入工作区，每个邀请码可注册一个账号，7天有效。</p></div><button className="primary" disabled={!active || busy || !!error || data.remaining <= 0} onClick={create}><Plus size={16}/>{busy ? '正在生成…' : '生成邀请码'}</button></div>
    {!active && <div className="inline-warning">账户已暂停，不能生成新邀请码。</div>}
    {error && <p role="alert">{error}<button className="text-link" onClick={() => load().catch(e => setError(e.message))}>重试</button></p>}
    <div className="notice"><UserPlus size={18}/><div>最多保留{data.limit}个未使用的邀请码，目前还可生成{data.remaining}个。完整邀请码只在生成时显示；请复制保存，不要分享你的安装包或官方 Key。</div></div>
    {created && <div className="member-invite-created"><h3>你的新邀请码</h3><code>{created.code}</code><p>有效期至 {date(created.expires_at)}</p><div className="table-actions"><button className="primary" onClick={() => copy(created.code)}><Clipboard size={15}/>复制邀请码</button><button className="small-button" onClick={() => copy(location.origin + '/login?invite=' + encodeURIComponent(created.code))}>复制注册链接</button></div></div>}
  </section><section className="panel"><div className="panel-head"><div><h2>我生成的邀请码</h2><p>可以查看使用情况或停用未分享的邀请码。</p></div></div>{data.items.length ? <div className="table-wrap"><table><thead><tr><th>邀请码</th><th>使用次数</th><th>有效期</th><th>状态</th><th>操作</th></tr></thead><tbody>{data.items.map((row: Row) => <tr key={row.id}><td><code>{row.prefix}••••</code></td><td>{row.used} / {row.max_uses}</td><td>{row.expires_at ? date(row.expires_at) : '未设置'}</td><td><span className="badge neutral">{!row.enabled ? '已停用' : row.used >= row.max_uses ? '已使用' : expired(row) ? '已过期' : '可使用'}</span></td><td>{row.enabled && row.used < row.max_uses && !expired(row) ? <button className="text-link" disabled={busy} onClick={() => disable(row.id)}>停用</button> : null}</td></tr>)}</tbody></table></div> : <p className="management-empty">还没有生成邀请码。点击「生成邀请码」邀请熟人加入。</p>}</section></>;
}
