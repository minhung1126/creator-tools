export function sortVideosByUploadTime(videos) {
  return [...videos].sort((a, b) => {
    const aTime = Date.parse(a.published_at || '');
    const bTime = Date.parse(b.published_at || '');
    const aHasTime = Number.isFinite(aTime);
    const bHasTime = Number.isFinite(bTime);
    if (aHasTime && bHasTime) return aTime - bTime || (a.sequence ?? 0) - (b.sequence ?? 0);
    if (aHasTime) return -1;
    if (bHasTime) return 1;
    return (a.sequence ?? 0) - (b.sequence ?? 0);
  });
}
