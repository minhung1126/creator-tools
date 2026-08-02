import React, { useEffect, useState } from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import YouTubeQuotaBanner from '../components/YouTubeQuotaBanner';

export default function ApiHealthPage() {
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setRefreshKey((key) => key + 1), 30000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="section-gap" style={{ maxWidth: 1240 }}>
      <div className="section-header" style={{ justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: '1.8rem' }}>API健康度</h1>
          <p className="section-desc">查看 YouTube API 配額估算與目前的安全上限狀態。</p>
        </div>
        <button className="btn btn-secondary" type="button" onClick={() => setRefreshKey((key) => key + 1)}>
          <RefreshCw size={16} />全部更新
        </button>
      </div>

      <YouTubeQuotaBanner refreshKey={refreshKey} />

      <div className="info-banner">
        <Activity size={16} color="var(--primary)" />
        <span>YouTube 數字是 Creator Tools 依官方 method cost 記錄的本地估算，不代表 Google Cloud project 的即時總用量。</span>
      </div>
    </div>
  );
}
