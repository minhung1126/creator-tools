import React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import YouTubeUploadPage from './YouTubeUploadPage';

export default function YoutubeUploadJobPage(props) {
  const { jobId } = useParams();
  const navigate = useNavigate();
  return <YouTubeUploadPage {...props} mode="job" jobId={jobId} navigate={navigate} />;
}

