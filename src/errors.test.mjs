import test from 'node:test';
import assert from 'node:assert/strict';
import { toUserMessage } from './shared/lib/errors.ts';

// T3.1：错误文案翻译的行为断言。这些分支一断，用户看到的就是笼统的"失败，请重试"，
// 而字段级原因（422 + detail.errors）会静默消失——所以逐条钉死。

/** 造一个 ApiError 形状的对象（errors.ts 用鸭子类型识别，无需真 ApiError 类）。 */
const apiError = (status, message, detail) => ({
  name: 'ApiError',
  code: status * 100,
  status,
  message,
  detail,
});

/** FastAPI `detail.errors()` 的形状。 */
const pydantic = (...errors) => errors;

test('网络失败（status 0）提示检查网络', () => {
  const result = toUserMessage(apiError(0, '网络请求失败: Failed to fetch'), '加载数据集');
  assert.equal(result.message, '加载数据集失败，请检查网络后重试');
  assert.equal(result.reason, undefined);
});

test('404 / 403 / 5xx 各自的固定文案', () => {
  assert.equal(toUserMessage(apiError(404, '数据不存在'), '加载数据集').message, '加载数据集失败：该数据不存在或已被删除');
  assert.equal(toUserMessage(apiError(403, '无权限'), '加载数据集').message, '加载数据集失败：当前账号没有查看权限');
  assert.equal(toUserMessage(apiError(500, '服务内部错误'), '加载数据集').message, '加载数据集失败：服务暂时不可用，请稍后重试');
});

test('409 保留信封里的业务文案（如 CSV 已存在导入任务），不翻译掉', () => {
  const result = toUserMessage(apiError(409, 'CSV 已存在导入任务'), '登记数据');
  assert.equal(result.message, '登记数据失败');
  assert.equal(result.reason, 'CSV 已存在导入任务');
});

test('422 把 Pydantic 字段路径翻成中文名，多条用「；」连接', () => {
  const err = apiError(422, '参数校验失败', pydantic(
    { loc: ['body', 'current_a'], msg: 'Input should be a valid number' },
    { loc: ['body', 'sample_rate'], msg: 'String should have at most 32 characters' },
  ));
  const result = toUserMessage(err, '登记数据');
  assert.equal(result.message, '登记数据失败：请检查填写内容');
  assert.equal(result.reason, '电流：Input should be a valid number；采样频率：String should have at most 32 characters');
});

test('422 的 loc 剥掉来源前缀与列表下标，未知字段回退为原字段名', () => {
  const err = apiError(422, '参数校验失败', pydantic(
    { loc: ['body', 0, 'unmapped_field'], msg: 'Field required' },
  ));
  assert.equal(toUserMessage(err, '提交标注').reason, 'unmapped_field：Field required');
});

test('422 但 detail 不是 errors 数组时不编造原因', () => {
  for (const detail of [undefined, null, 'boom', { msg: 'x' }]) {
    const result = toUserMessage(apiError(422, '参数校验失败', detail), '登记数据');
    assert.equal(result.message, '登记数据失败：请检查填写内容');
    assert.equal(result.reason, undefined);
  }
});

test('未归类状态码落入「请重试」兜底，并带上信封原文（除非它就是「请求失败」）', () => {
  assert.deepEqual(toUserMessage(apiError(418, '我是茶壶'), '加载数据集'), {
    message: '加载数据集失败，请重试',
    reason: '我是茶壶',
  });
  assert.equal(toUserMessage(apiError(418, '请求失败'), '加载数据集').reason, undefined);
});

test('非 ApiError 的异常也能出文案', () => {
  assert.equal(toUserMessage(new Error('文件已上传但关联失败'), '登记数据').message, '登记数据失败：文件已上传但关联失败');
  assert.equal(toUserMessage(undefined, '登记数据').message, '登记数据失败，请重试');
  assert.equal(toUserMessage('炸了', '登记数据').message, '登记数据失败，请重试');
});
