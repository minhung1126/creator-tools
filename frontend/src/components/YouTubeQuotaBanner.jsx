import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, AlertTriangle, Clock3, Database, RefreshCw, ShieldAlert } from 'lucide-react';
import { api } from '../services/api';
import { StatusMessage } from './StatusMessage';

const STATE_META = {
  normal: { label: '正常', Icon: Activity },
  warning: { label: '接近安全上限', Icon: AlertTriangle },
  safety_blocked: { label: '已達安全上限', Icon: AlertTriangle },
  confirmed_exhausted: { label: 'Google 已確認用完', Icon: ShieldAlert },
};
const DEFAULT_AVAILABLE_SLOTS = ['primary'];

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

function formatLastUpdated(value) {
  if (!value) return '未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未知';
  return date.toLocaleString('zh-TW');
}

function units(value) {
  return Number(value || 0).toLocaleString();
}

function slotLabel(slot) {
  return slot === 'primary' ? '主要授權組合' : '次要授權組合';
}

export default function YouTubeQuotaBanner({ refreshKey = 0, compact = false, activeSlot = 'primary', availableSlots = DEFAULT_AVAILABLE_SLOTS }) {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [errorSlot, setErrorSlot] = useState(null);
  const [selectedSlot, setSelectedSlot] = useState(activeSlot || 'primary');
  const [loadedSlot, setLoadedSlot] = useState(null);
  const [lastUpdatedBySlot, setLastUpdatedBySlot] = useState({});
  const requestIdRef = useRef(0);
  const slotOptions = useMemo(() => (availableSlots.length ? availableSlots : [activeSlot || 'primary']), [activeSlot, availableSlots]);

  useEffect(() => {
    const nextSlots = availableSlots.length ? availableSlots : [activeSlot || 'primary'];
    const nextSlot = nextSlots.includes(activeSlot) ? activeSlot : nextSlots[0];
    setSelectedSlot((current) => (nextSlots.includes(current) ? (current === activeSlot ? current : nextSlot) : nextSlot));
  }, [activeSlot, availableSlots]);

  const loadUsage = useCallback(async () => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const requestSlot = selectedSlot;
    setLoading(true);
    setError('');
    setErrorSlot(null);
    setUsage(null);
    setLoadedSlot(null);
    try {
      const nextUsage = await api.getYoutubeQuotaUsage(requestSlot);
      if (requestId !== requestIdRef.current) return;
      setUsage(nextUsage);
      setLoadedSlot(requestSlot);
      setLastUpdatedBySlot((current) => ({
        ...current,
        [requestSlot]: nextUsage?.last_updated_at || new Date().toISOString(),
      }));
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      setError(err?.message || '無法讀取配額資料，請重試。');
      setErrorSlot(requestSlot);
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [selectedSlot]);

  const handleSlotChange = (event) => {
    const nextSlot = event.target.value;
    setSelectedSlot(nextSlot);
    setUsage(null);
    setLoadedSlot(null);
    setError('');
    setErrorSlot(null);
    setLoading(true);
  };

  useEffect(() => {
    loadUsage();
  }, [loadUsage, refreshKey]);

  const updatedAt = lastUpdatedBySlot[selectedSlot];
  const currentUsage = loadedSlot === selectedSlot ? usage : null;
  if (error && errorSlot === selectedSlot && !currentUsage) {
    return (
      <div className="glass-panel quota-status-panel">
        <StatusMessage
          tone="error"
          status="failed"
          title={`${slotLabel(selectedSlot)}配額更新失敗`}
          action={<button type="button" className="btn btn-secondary status-message-action" onClick={loadUsage} disabled={loading}><RefreshCw size={14} aria-hidden="true" />重試</button>}
        >
          <span>{error}</span>
          <small>{updatedAt ? `資料已過期；最後成功更新：${formatLastUpdated(updatedAt)}` : '目前沒有可用的配額資料。'}</small>
        </StatusMessage>
      </div>
    );
  }

  if (loading || !currentUsage) {
    return (
      <div className={`glass-panel quota-status-panel${compact ? ' quota-status-panel-compact' : ''}`}>
        <StatusMessage title="讀取中…">
          <RefreshCw size={16} className="spin" aria-hidden="true" />
          更新中…
        </StatusMessage>
      </div>
    );
  }

  const stateKey = Object.prototype.hasOwnProperty.call(STATE_META, currentUsage?.state) ? currentUsage.state : 'normal';
  const stateMeta = STATE_META[stateKey];
  const StateIcon = currentUsage?.confirmed_by_google ? ShieldAlert : stateMeta.Icon;
  const usageSlot = currentUsage?.slot || currentUsage?.youtube_slot || currentUsage?.youtube?.slot || selectedSlot;
  const used = Number(currentUsage?.estimated_used_units ?? 0);
  const limit = Number(currentUsage?.configured_project_limit ?? 10000);
  const effective = Number(currentUsage?.effective_available_units ?? 0);
  const policyCap = Number(currentUsage?.policy_cap_units ?? Math.max(limit - Number(currentUsage?.safety_buffer_units || 0), 0));
  const percent = Math.min(Math.max((used / Math.max(limit, 1)) * 100, 0), 100);
  const confirmed = stateKey === 'confirmed_exhausted' || currentUsage?.confirmed_by_google;

  return (
    <section className={`glass-panel quota-banner quota-state-${stateKey}${compact ? ' quota-banner-compact' : ''}`} style={{ '--quota-percent': `${percent}%` }}>
      <div className="quota-banner-header">
        <div className="quota-banner-heading">
          <div className="quota-state-icon"><StateIcon size={20} aria-hidden="true" /></div>
          <div>
            <div className="quota-title-row">
              <strong>YouTube 配額今日估算用量</strong>
              <span className="badge quota-state-badge">{stateMeta.label}</span>
              <span className="badge badge-info quota-slot-actual">資料 slot：{slotLabel(usageSlot)}</span>
              <select aria-label="YouTube 授權組合" className="form-select quota-slot-select" value={selectedSlot} onChange={handleSlotChange}>
                {slotOptions.map((slot) => <option value={slot} key={slot}>{slotLabel(slot)}</option>)}
              </select>
            </div>
            <div className="quota-usage-value">
              {units(used)} / {units(limit)}
              <span>單位（Creator Tools 估算）</span>
            </div>
          </div>
        </div>
        <button type="button" className="btn btn-secondary quota-refresh-button" onClick={loadUsage} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} aria-hidden="true" />更新
        </button>
      </div>

      {!compact && <div className="quota-progress-track" role="progressbar" aria-label="配額使用比例" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(percent)}><div className="quota-progress-value" /></div>}

      <div className="quota-meta">
        <span><Database size={14} aria-hidden="true" />系統可用 {units(effective)} 單位（安全上限 {units(policyCap)}）</span>
        <span>官方預設 {units(currentUsage?.official_default_limit || 10000)} · 專案設定 {units(limit)} · 安全預留 {units(currentUsage?.safety_buffer_units)}</span>
        <span><Clock3 size={14} aria-hidden="true" />Google 官方重設：{formatPacificReset(currentUsage?.reset_at)} PT；本地時間：{formatLocalReset(currentUsage?.reset_at)}</span>
        <span>最後更新：{formatLastUpdated(updatedAt)}</span>
      </div>

      {confirmed && <div className="quota-alert quota-alert-error"><AlertTriangle size={16} aria-hidden="true" /><span>Google 已確認配額耗盡；系統已停止新的 YouTube 請求，直到官方重設。</span></div>}
      {!confirmed && stateKey === 'safety_blocked' && <div className="quota-alert quota-alert-warning">Creator Tools 已達自訂安全上限，等待官方重設後自動恢復。</div>}
      {!confirmed && currentUsage?.reason && <div className="quota-alert quota-alert-warning"><AlertTriangle size={16} aria-hidden="true" /><span>{currentUsage.reason}</span></div>}

      {!compact && currentUsage?.methods?.length > 0 && <div className="quota-methods">{currentUsage.methods.map((item) => <span key={`${item.method}-${item.cost_per_call}`} className="badge badge-info">{item.method}: {item.calls} 次 × {item.cost_per_call} = {units(item.units)} 單位</span>)}</div>}
      {!compact && <p className="quota-note">{currentUsage?.note || '本數字只統計 Creator Tools，屬於估算，不是 Google Cloud 專案的即時總用量。'}{currentUsage?.quota_rules_verified_at ? ` 官方規則核對日期：${currentUsage.quota_rules_verified_at}。` : ''}</p>}
    </section>
  );
}
