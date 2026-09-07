const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../../web_app/templates/signal_explanation.html'), 'utf8');

test('解释刷新被拒绝时在原页面显示中文错误', async () => {
  const scriptMatch = template.match(/<script>([\s\S]*?)<\/script>/);
  assert.ok(scriptMatch, '解释页面应包含提交反馈脚本');

  let submitHandler;
  const errorBox = { hidden: true, textContent: '' };
  const button = { disabled: false, textContent: '重新生成解释' };
  const form = {
    action: '/explain/signal/20260525/000012.SZ/refresh',
    addEventListener: (_, handler) => { submitHandler = handler; },
    querySelector: selector => selector === '[data-explanation-error]' ? errorBox : button,
  };
  const document = { querySelectorAll: () => [form] };
  const window = { location: { assign() { throw new Error('拒绝时不应跳转'); } } };
  const fetch = async () => ({
    ok: false,
    status: 403,
    json: async () => ({ detail: '当前服务为只读模式，未启用写操作' }),
  });

  vm.runInNewContext(scriptMatch[1], { document, window, fetch });
  await submitHandler({ preventDefault() {} });

  assert.equal(errorBox.hidden, false);
  assert.equal(errorBox.textContent, '当前服务为只读模式，未启用写操作');
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, '重新生成解释');
});
