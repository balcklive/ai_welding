import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(__dirname, 'features/analysis/AnalysisWorkspace.tsx'), 'utf8');

test('analysis timeline is driven by the real signal duration, not the demo constant', () => {
  // 时间轴时长来自 getSignals 的 duration（18s 的真实信号曾画成固定 5.42s 的演示坐标）
  assert.match(source, /setSignalDuration\(data\.duration/);
  assert.match(source, /const timelineDur = signalDuration \?\? dur/);
  assert.match(source, /dur=\{timelineDur\}/);
  // 起收弧事件来自接口 events，不再写死演示时刻
  assert.match(source, /setSignalEvents\(data\.events\)/);
  assert.doesNotMatch(source, /00:00\.42|00:04\.28|00:04\.86/);
  // 波形异常色带来自真实 anomalies，不再用演示区段常量
  assert.doesNotMatch(source, /anomalA|anomalB/);
});
