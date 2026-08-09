import React, { useEffect, useState } from 'react';
import { Activity, AlertTriangle, Clock3, Database, RefreshCw, ShieldAlert } from 'lucide-react';
import { api } from '../services/api';

const STATE_STYLE = {
  normal: { color: '#b9b9b0', background: '#2b2b29', border: '#50504a', label: '正常' },
  warning: { color: '#d6b377', background: '#352d20', border: '#685333', label: '接近安全上限' },
  safety_blocked: { color: '#d8ae83', background: '#362b23', border: '#6a503b', label: '已達安全上限' },
  confirmed_exhausted: { color: '#d49393', background: '#332426', border: '#624044', label: 'Google 已確認用完' },
};

function formatPacificReset(value) {
  if (!value) return '未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未知';
  return new Intl.DateTimeFormat('zh-TW', {
    timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date).replace(/-/g, '/');
}

function formatLocalReset(value) {
  if (!value) return '未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未知';
  return new Intl.DateTimeFormat('zh-TW', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date).replace(/-/g, '/');
}

function units(value) {
  return Number(value || 0).toLocaleString();
}

export default function YouTubeQuotaBanner({ refreshKey = 0, compact = false }) {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadUsage = async () => {
    setLoading(true);
    setError('');
    try {
      setUsage(await api.getYoutubeQuotaUsage());
    } catch (err) {
      setError(err.message || '無法讀取配額估算');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadUsage(); }, [refreshKey]);

  if (loading && !usage) {
    return <div className="glass-panel" style={{ padding: compact ? '10px 14px' : '14px 18px', display: 'flex', alignItems: 'center', gap: '10px' }}><RefreshCw size={17} className="spin" color="var(--primary)" /><span style={{ color: 'var(--text-muted)', fontSize: '0.86rem' }}>讀取 YouTube quota 估算中...</span></div>;
  }

  if (error && !usage) {
    return <div className="glass-panel" style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}><span style={{ color: '#d49393', fontSize: '0.86rem' }}>YouTube quota 估算讀取失敗：{error}</span><button type="button" className="btn" onClick={loadUsage} style={{ padding: '6px 10px' }}><RefreshCw size={14} />重試</button></div>;
  }

  const style = STATE_STYLE[usage?.state] || STATE_STYLE.normal;
  const used = Number(usage?.estimated_used_units ?? 0);
  const limit = Number(usage?.configured_project_limit ?? 10000);
  const effective = Number(usage?.effective_available_units ?? 0);
  const policyCap = Number(usage?.policy_cap_units ?? Math.max(limit - Number(usage?.safety_buffer_units || 0), 0));
  const percent = Math.min(Math.max((used / Math.max(limit, 1)) * 100, 0), 100);
  const confirmed = usage?.state === 'confirmed_exhausted' || usage?.confirmed_by_google;

  return (
    <div className="glass-panel" style={{ padding: compact ? '12px 15px' : '18px 20px', border: `1px solid ${style.border}`, background: style.background }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
          <div style={{ padding: '9px', borderRadius: '10px', background: style.background, display: 'flex' }}>
            {confirmed ? <ShieldAlert size={20} color={style.color} /> : usage?.state === 'safety_blocked' ? <AlertTriangle size={20} color={style.color} /> : <Activity size={20} color={style.color} />}
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', flexWrap: 'wrap' }}>
              <strong style={{ color: 'var(--text-main)', fontSize: '1rem' }}>YouTube API 今日估算用量</strong>
              <span className="badge" style={{ color: style.color, borderColor: style.border, background: style.background }}>{style.label}</span>
            </div>
            <div style={{ marginTop: '5px', color: 'var(--text-main)', fontSize: '1.35rem', fontWeight: 700 }}>
              {units(used)} / {units(limit)}
              <span style={{ color: 'var(--text-muted)', fontSize: '0.82rem', fontWeight: 500, marginLeft: '7px' }}>units（Creator Tools 估算）</span>
            </div>
          </div>
        </div>
        <button type="button" className="btn" onClick={loadUsage} disabled={loading} style={{ padding: '7px 11px' }}><RefreshCw size={14} className={loading ? 'spin' : ''} />更新</button>
      </div>

      {!compact && <div style={{ height: '8px', borderRadius: '999px', background: 'var(--surface-raised)', overflow: 'hidden', marginTop: '14px' }}><div style={{ height: '100%', width: `${percent}%`, background: style.color, transition: 'width 180ms ease' }} /></div>}

      <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap', marginTop: compact ? '8px' : '12px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}><Database size={14} />系統可用 {units(effective)} units（安全 cap {units(policyCap)}）</span>
        <span>官方預設 {units(usage?.official_default_limit || 10000)} · project 設定 {units(limit)} · 安全保留 {units(usage?.safety_buffer_units)}</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}><Clock3 size={14} />官方重設：{formatPacificReset(usage?.reset_at)} PT；本地時間：{formatLocalReset(usage?.reset_at)}</span>
      </div>

      {confirmed && <div style={{ marginTop: '12px', color: '#dca3a3', fontSize: '0.85rem', display: 'flex', gap: '7px', alignItems: 'flex-start' }}><AlertTriangle size={16} /><span>Google 已確認 `quotaExceeded`；系統已停止新的 YouTube request，直到官方重設。Google Cloud project 的其他應用程式也可能消耗額度。</span></div>}
      {!confirmed && usage?.state === 'safety_blocked' && <div style={{ marginTop: '12px', color: '#d8ae83', fontSize: '0.85rem' }}>Creator Tools 已達自訂安全上限，等待官方重設後自動恢復。</div>}

      {!compact && usage?.methods?.length > 0 && <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '12px' }}>{usage.methods.map((item) => <span key={`${item.method}-${item.cost_per_call}`} className="badge badge-info" style={{ fontSize: '0.72rem' }}>{item.method}: {item.calls} 次 × {item.cost_per_call} = {units(item.units)} units</span>)}</div>}
      {!compact && <p style={{ marginTop: '10px', color: 'var(--text-dim)', fontSize: '0.72rem', lineHeight: 1.5 }}>{usage?.note || '本數字只統計 Creator Tools，屬於估算，不是 Google 官方即時 project usage。'}{usage?.quota_rules_verified_at ? ` 官方規則核對日期：${usage.quota_rules_verified_at}。` : ''}</p>}
    </div>
  );
}
