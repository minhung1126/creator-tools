import React, { useEffect, useState } from 'react';
import { Activity, AlertTriangle, Clock3, Database, Gauge, RefreshCw } from 'lucide-react';
import { api } from '../services/api';

function formatPercent(value) {
  return value === null || value === undefined ? '—' : `${Number(value).toLocaleString('zh-TW', { maximumFractionDigits: 2 })}%`;
}

function formatDate(value) {
  if (!value) return '尚未取得';
  try {
    return new Intl.DateTimeFormat('zh-TW', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function usageStatus(percent) {
  if (percent === null || percent === undefined) return { label: '尚未取得 Meta 回報', color: 'var(--text-muted)' };
  if (percent >= 100) return { label: '可能已達 Meta 限制', color: '#f87171' };
  if (percent >= 80) return { label: '接近 Meta 限制', color: '#fbbf24' };
  return { label: '目前正常', color: '#86efac' };
}

export default function InstagramApiUsageBanner({ refreshKey = 0 }) {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadUsage = async () => {
    setLoading(true);
    setError('');
    try {
      setUsage(await api.getInstagramApiUsage());
    } catch (err) {
      setError(err.message || '無法讀取 Instagram API 使用情況');
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
        <RefreshCw size={17} className="spin" color="#ec4899" />
        <span style={{ color: 'var(--text-muted)', fontSize: '0.86rem' }}>讀取 Instagram API 使用情況中...</span>
      </div>
    );
  }

  if (error && !usage) {
    return (
      <div className="glass-panel" style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
        <span style={{ color: '#f87171', fontSize: '0.86rem' }}>Instagram API 使用情況讀取失敗：{error}</span>
        <button type="button" className="btn" onClick={loadUsage} style={{ padding: '6px 10px' }}>
          <RefreshCw size={14} /> 重試
        </button>
      </div>
    );
  }

  const meta = usage?.meta_usage || {};
  const percent = usage?.usage_percent ?? null;
  const progress = Math.min(Math.max(percent || 0, 0), 100);
  const status = usageStatus(percent);
  const lastError = usage?.last_error;

  return (
    <div className="glass-panel" style={{ padding: '18px 20px', border: '1px solid rgba(236, 72, 153, 0.38)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
          <div style={{ padding: '9px', borderRadius: '10px', background: 'rgba(236, 72, 153, 0.14)', display: 'flex' }}>
            <Activity size={20} color="#ec4899" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', flexWrap: 'wrap' }}>
              <strong style={{ color: '#fff', fontSize: '1rem' }}>Instagram API 使用情況</strong>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>Meta x-app-usage 回報</span>
            </div>
            <div style={{ marginTop: '5px', color: '#fff', fontSize: '1.35rem', fontWeight: 700 }}>
              {percent === null ? '尚未取得' : `${formatPercent(percent)} / 100%`}
              <span style={{ color: status.color, fontSize: '0.82rem', fontWeight: 500, marginLeft: '9px' }}>{status.label}</span>
            </div>
          </div>
        </div>

        <button type="button" className="btn" onClick={loadUsage} disabled={loading} style={{ padding: '7px 11px' }}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> 更新
        </button>
      </div>

      <div style={{ height: '8px', borderRadius: '999px', background: 'rgba(148, 163, 184, 0.16)', overflow: 'hidden', marginTop: '14px' }}>
        <div style={{ height: '100%', width: `${progress}%`, background: 'linear-gradient(90deg, #ec4899, #f97316)', transition: 'width 180ms ease' }} />
      </div>

      <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap', marginTop: '12px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
          <Gauge size={14} /> 呼叫量 {formatPercent(meta.call_volume)} · CPU {formatPercent(meta.cpu_time)} · 時間 {formatPercent(meta.total_time)}
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
          <Database size={14} /> 剩餘估算 {formatPercent(usage?.remaining_percent)}
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
          <Database size={14} /> 本系統今日請求 {Number(usage?.requests_today || 0).toLocaleString()} 次
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
          <Clock3 size={14} /> Meta 回報更新：{formatDate(meta.observed_at)}
        </span>
      </div>

      {lastError?.message && (
        <div className="info-banner" style={{ marginTop: '12px', color: '#fbbf24' }}>
          <AlertTriangle size={15} />
          <span>最近 Meta 錯誤：{lastError.message}{lastError.code !== null && lastError.code !== undefined ? `（code ${lastError.code}）` : ''}</span>
        </div>
      )}

      {usage?.methods?.length > 0 && (
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '12px' }}>
          {usage.methods.map((item) => (
            <span key={item.endpoint} className="badge badge-info" style={{ fontSize: '0.72rem' }}>
              {item.endpoint}: {item.calls} 次
            </span>
          ))}
        </div>
      )}

      <p style={{ marginTop: '10px', color: 'var(--text-dim)', fontSize: '0.72rem', lineHeight: 1.5 }}>
        {usage?.note}
        {usage?.updated_at ? ` 最近請求紀錄：${formatDate(usage.updated_at)}。` : ''}
      </p>
    </div>
  );
}
