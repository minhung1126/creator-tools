import React from 'react';
import { ExternalLink, Globe } from 'lucide-react';

const DEPLOYMENT_DOCS = 'https://github.com/minhung1126/creator-tools/blob/main/docs/DEPLOYMENT.md';

export default function SystemInfoPage({ sysSettings = {} }) {
  return (
    <div className="section-gap settings-page">
      <header className="page-header">
        <h1>系統／部署資訊</h1>
        <p className="section-desc">目前部署環境提供的公開網址、監聽位址與前端網址（唯讀）。</p>
      </header>
      <section className="glass-panel card-padding settings-card card-stack">
        <h2 className="settings-heading"><Globe size={20} /> 系統／部署資訊（唯讀）</h2>
        <div className="settings-grid">
          <div className="form-group"><label className="form-label">對外公開網址（PUBLIC_BASE_URL）</label><input className="form-input" value={sysSettings.public_base_url || ''} readOnly /></div>
          <div className="form-group"><label className="form-label">伺服器監聽位址（BIND_HOST）</label><input className="form-input" value={sysSettings.bind_host || ''} readOnly /></div>
          <div className="form-group"><label className="form-label">Frontend URL</label><input className="form-input" value={sysSettings.frontend_url || ''} readOnly /></div>
        </div>
        <p className="section-desc">這些值由部署環境的 `.env` 管理；PUBLIC_BASE_URL 也是 Google OAuth callback 的來源。</p>
        <a className="btn btn-secondary settings-inline-button" href={DEPLOYMENT_DOCS} target="_blank" rel="noreferrer">開啟部署文件 <ExternalLink size={14} /></a>
      </section>
    </div>
  );
}

