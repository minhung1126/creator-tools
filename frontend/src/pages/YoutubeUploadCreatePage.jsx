import React from 'react';
import { useNavigate } from 'react-router-dom';
import YouTubeUploadPage from './YouTubeUploadPage';

export default function YoutubeUploadCreatePage(props) {
  const navigate = useNavigate();
  return <YouTubeUploadPage {...props} mode="create" navigate={navigate} />;
}

