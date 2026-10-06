import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// A successful CLI exit is insufficient when @source paths match no templates.
test('compiled Tailwind includes navigation, accessibility and responsive utilities', () => {
  const css = readFileSync(new URL('../static/css/app.min.css', import.meta.url), 'utf8');
  for (const selector of ['.sr-only{', '.flex{', '.hidden{', '.items-center{', '.bg-slate-950{', '.md\\:flex{']) {
    assert.ok(css.includes(selector), `Missing template utility ${selector}`);
  }
});
