export const PAGE_RECOVERY_PARAM = '__ct_resume';

function documentPath(url) {
  return `${url.pathname}${url.search}${url.hash}`;
}

export function buildPageRecoveryUrl(href, timestamp = Date.now()) {
  const url = new URL(href);
  url.searchParams.set(PAGE_RECOVERY_PARAM, String(timestamp));
  return url.toString();
}

export function clearPageRecoveryParam({
  href = window.location.href,
  replaceState = (nextPath) => window.history.replaceState(window.history.state, document.title, nextPath),
} = {}) {
  const url = new URL(href);
  if (!url.searchParams.has(PAGE_RECOVERY_PARAM)) return false;
  url.searchParams.delete(PAGE_RECOVERY_PARAM);
  replaceState(documentPath(url));
  return true;
}

export function recoverPage({
  href = window.location.href,
  navigate = (target) => window.location.replace(target),
  timestamp = Date.now(),
} = {}) {
  const target = buildPageRecoveryUrl(href, timestamp);
  navigate(target);
  return target;
}
