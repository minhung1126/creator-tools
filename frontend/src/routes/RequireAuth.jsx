import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { buildLoginPath, getCurrentPath, PATHS } from './paths';

export default function RequireAuth({ authStatus, authUser, children }) {
  const location = useLocation();
  if (authStatus === 'authenticated' && authUser) return children;
  if (authStatus === 'reconnecting' && authUser) return children;

  const requestedPath = getCurrentPath(location);
  return <Navigate replace to={buildLoginPath(requestedPath) || PATHS.login} />;
}

