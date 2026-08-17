import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const indexHtml = readFileSync('index.html', 'utf8');

describe('static HTML loading fallback', () => {
  it('keeps visible recovery content inside #root without inline JavaScript', () => {
    expect(indexHtml).toContain('<div id="root">');
    expect(indexHtml).toContain('Creator Tools 載入中');
    expect(indexHtml).toContain('若長時間沒有顯示，請重新載入');
    expect(indexHtml).toContain('<a href="/">重新載入</a>');
    expect(indexHtml).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/i);
  });
});
