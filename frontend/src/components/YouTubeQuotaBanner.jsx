import React, { useEffect, useState } from 'react';
import { Activity, Clock3, Database, RefreshCw } from 'lucide-react';
import { api } from '../services/api';

export default function YouTubeQuotaBanner({ refreshKey = 0 }) {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadUsage = async () => {
    setLoading(true);
    setError('');
    try {
      setUsage(await api.getYoutubeQuotaUsage());
    } catch (err) {
      setError(err.message || '無法讀取配額紀錄');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsage();
  }, [refreshKey]);

  if (loading && !usage) {
    return (
      <div className="glass-panel" style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', gap: '10px' }}>
        <RefreshCw size={17} className="spin" color="var(--primary)" />
        <span style={{ color: 'var(--text-muted)', fontSize: '0.86rem' }}>讀取 YouTube API 配額紀錄中...</span>
      </div>
    );
  }

  if (error && !usage) {
    return (
      <div className="glass-panel" style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
        <span style={{ color: '#f87171', fontSize: '0.86rem' }}>YouTube API 配額紀錄讀取失敗：{error}</span>
        <button type="button" className="btn" onClick={loadUsage} style={{ padding: '6px 10px' }}>
          <RefreshCw size={14} /> 重試
        </button>
      </div>
    );
  }

  const percent = Math.min(Math.max(usage?.usage_percent || 0, 0), 100);
  const resetDate = usage?.reset_at ? new Date(usage.reset_at) : null;
  const resetPacificText = resetDate
    ? resetDate.toLocaleString('zh-TW', { timeZone: usage?.reset_timezone || 'America/Los_Angeles' })
    : '未知';
  const resetLocalText = resetDate ? resetDate.toLocaleString() : '未知';

  return (
    <div className="glass-panel" style={{ padding: '18px 20px', border: '1px solid rgba(99, 102, 241, 0.35)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
          <div style={{ padding: '9px', borderRadius: '10px', background: 'rgba(99, 102, 241, 0.14)', display: 'flex' }}>
            <Activity size={20} color="var(--primary)" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', flexWrap: 'wrap' }}>
              <strong style={{ color: '#fff', fontSize: '1rem' }}>YouTube API 今日估算用量</strong>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>依官方每次 request 成本計算</span>
            </div>
            <div style={{ marginTop: '5px', color: '#fff', fontSize: '1.35rem', fontWeight: 700 }}>
              {usage?.used_units?.toLocaleString()} / {usage?.daily_limit?.toLocaleString()}
              <span style={{ color: 'var(--text-muted)', fontSize: '0.82rem', fontWeight: 500, marginLeft: '7px' }}>units</span>
            </div>
          </div>
        </div>

        <button type="button" className="btn" onClick={loadUsage} disabled={loading} style={{ padding: '7px 11px' }}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> 更新
        </button>
      </div>

      <div style={{ height: '8px', borderRadius: '999px', background: 'rgba(148, 163, 184, 0.16)', overflow: 'hidden', marginTop: '14px' }}>
        <div style={{ height: '100%', width: `${percent}%`, background: 'linear-gradient(90deg, #6366f1, #ec4899)', transition: 'width 180ms ease' }} />
      </div>

      <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap', marginTop: '12px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
          <Database size={14} /> 剩餘估算 {usage?.remaining_units?.toLocaleString()} units
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
          <Clock3 size={14} /> 太平洋時間重設：{resetPacificText}（本地：{resetLocalText}）
        </span>
        <span>播放清單排序使用 yt-dlp；私人資料補齊仍可能使用 videos.list。</span>
      </div>

      {usage?.methods?.length > 0 && (
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '12px' }}>
          {usage.methods.map((item) => (
            <span key={item.method} className="badge badge-info" style={{ fontSize: '0.72rem' }}>
              {item.method}: {item.calls} 次 × {item.cost_per_call} = {item.units} units
            </span>
          ))}
        </div>
      )}

      <p style={{ marginTop: '10px', color: 'var(--text-dim)', fontSize: '0.72rem', lineHeight: 1.5 }}>
        {usage?.note}
        {usage?.quota_costs_verified_at ? ` 官方費用表核對日期：${usage.quota_costs_verified_at}。` : ''}
      </p>
    </div>
  );
}
