import React, { useEffect, useState } from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import YouTubeQuotaBanner from '../components/YouTubeQuotaBanner';
import InstagramApiUsageBanner from '../components/InstagramApiUsageBanner';

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
          <p className="section-desc">集中查看 YouTube API 配額與 Instagram API 使用率、限流及最近錯誤。</p>
        </div>
        <button className="btn btn-secondary" type="button" onClick={() => setRefreshKey((key) => key + 1)}>
          <RefreshCw size={16} />全部更新
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 460px), 1fr))', gap: 20 }}>
        <YouTubeQuotaBanner refreshKey={refreshKey} />
        <InstagramApiUsageBanner refreshKey={refreshKey} />
      </div>

      <div className="info-banner">
        <Activity size={16} color="var(--primary)" />
        <span>YouTube 數字是 Creator Tools 的 quota 估算；Instagram 數字來自 Meta 回應的 x-app-usage 滾動使用率。</span>
      </div>
    </div>
  );
}
