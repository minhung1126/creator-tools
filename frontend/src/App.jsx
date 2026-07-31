import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import DashboardPage from './pages/DashboardPage';
import BatchUpdatePage from './pages/BatchUpdatePage';
import PublishCleanerPage from './pages/PublishCleanerPage';
import SettingsPage from './pages/SettingsPage';
import { api } from './services/api';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [authUser, setAuthUser] = useState(null);
  const [sysSettings, setSysSettings] = useState({});
  const [loading, setLoading] = useState(true);

  const fetchUser = async () => {
    try {
      const res = await api.getUserStatus();
      if (res.authenticated) {
        setAuthUser(res.user);
      } else {
        setAuthUser(null);
      }
    } catch (err) {
      console.error('Failed to fetch user status:', err);
      setAuthUser(null);
    }
  };

  const fetchSettings = async () => {
    try {
      const data = await api.getSettings();
      setSysSettings(data || {});
    } catch (err) {
      console.error('Failed to fetch system settings:', err);
    }
  };

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      await fetchSettings();
      await fetchUser();
      
      // Check location hash for OAuth callback return
      const hash = window.location.hash;
      if (hash.includes('auth_success=1')) {
        alert('Google 帳號連線成功！');
        window.location.hash = '';
        await fetchUser();
      } else if (hash.includes('auth_error=')) {
        const errorText = decodeURIComponent(hash.split('auth_error=')[1] || '');
        alert(`Google 帳號連線失敗：${errorText}`);
        window.location.hash = '';
      }
      setLoading(false);
    };

    init();
  }, []);

  const handleLogout = async () => {
    try {
      await api.logout();
      setAuthUser(null);
      alert('已成功登出 Google 帳號！');
    } catch (err) {
      console.error('Logout error:', err);
    }
  };

  return (
    <div className="app-container">
      <Navbar 
        activeTab={activeTab} 
        setActiveTab={setActiveTab} 
        authUser={authUser}
        onLogout={handleLogout}
      />

      <main className="main-content">
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', color: 'var(--text-muted)' }}>
            系統初始化集中...
          </div>
        ) : (
          <>
            {activeTab === 'dashboard' && (
              <DashboardPage 
                authUser={authUser} 
                sysSettings={sysSettings} 
                setActiveTab={setActiveTab} 
              />
            )}
            {activeTab === 'batch_update' && (
              <BatchUpdatePage 
                sysSettings={sysSettings} 
                authUser={authUser} 
              />
            )}
            {activeTab === 'publish_clean' && (
              <PublishCleanerPage 
                sysSettings={sysSettings} 
                authUser={authUser} 
              />
            )}
            {activeTab === 'settings' && (
              <SettingsPage 
                authUser={authUser} 
                sysSettings={sysSettings} 
                refreshSettings={fetchSettings}
                refreshUser={fetchUser}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}
