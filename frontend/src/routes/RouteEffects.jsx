import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

const TITLES = [
  [/^\/login$/, '登入｜Creator Tools'],
  [/^\/dashboard$/, '儀表板｜Creator Tools'],
  [/^\/system\/health$/, 'API 健康度｜Creator Tools'],
  [/^\/system\/info$/, '系統／部署資訊｜Creator Tools'],
  [/^\/youtube\/uploads\/new$/, '建立 YouTube 上傳｜Creator Tools'],
  [/^\/youtube\/uploads\//, 'YouTube 上傳工作｜Creator Tools'],
  [/^\/youtube\/drafts\/videos$/, 'Video 草稿｜Creator Tools'],
  [/^\/youtube\/drafts\/shorts$/, 'Shorts 草稿｜Creator Tools'],
  [/^\/youtube\/publish-cleanup$/, '發布草稿｜Creator Tools'],
  [/^\/youtube\/settings\/connections$/, 'YouTube 授權組合｜Creator Tools'],
  [/^\/youtube\/settings\/routing$/, 'YouTube Routing｜Creator Tools'],
  [/^\/youtube\/settings\/quota$/, 'YouTube Quota｜Creator Tools'],
  [/^\/youtube\/settings\/playlist$/, '預設播放清單｜Creator Tools'],
  [/^\/sheets\/copy$/, 'Sheet 內容複製｜Creator Tools'],
  [/^\/settings\/google$/, 'Google 帳號與授權｜Creator Tools'],
  [/^\/settings\/sheets$/, '預設 Google Sheet｜Creator Tools'],
];

export function titleForPath(pathname) {
  return TITLES.find(([pattern]) => pattern.test(pathname))?.[1] || '頁面不存在｜Creator Tools';
}

export default function RouteEffects() {
  const location = useLocation();

  useEffect(() => {
    document.title = titleForPath(location.pathname);
    if (!window.navigator.userAgent.includes('jsdom')) window.scrollTo?.(0, 0);
  }, [location.pathname, location.search]);

  return null;
}
