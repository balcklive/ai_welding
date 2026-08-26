import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const viteConfig = fs.readFileSync(path.join(__dirname, '..', 'vite.config.ts'), 'utf8');

test('production assets use the root deployment path', () => {
  assert.match(viteConfig, /base:\s*['"]\/['"]/);
  assert.doesNotMatch(viteConfig, /base:\s*['"]\/ai_welding\/['"]/);
});
