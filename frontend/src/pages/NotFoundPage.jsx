import React from 'react';
import { Link } from 'react-router-dom';
import { PATHS } from '../routes/paths';

export default function NotFoundPage() {
  return (
    <div className="section-gap error-state" role="status">
      <div className="glass-panel card-padding card-stack">
        <h1>找不到頁面</h1>
        <p className="section-desc">這個網址不存在，或頁面已經移動。</p>
        <Link className="btn btn-primary" to={PATHS.dashboard}>返回 Dashboard</Link>
      </div>
    </div>
  );
}

