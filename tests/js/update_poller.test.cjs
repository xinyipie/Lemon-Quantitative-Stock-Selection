const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// 直接执行模板里的实际脚本，浏览器边界使用可控替身。
const template = fs.readFileSync(path.join(__dirname, '../../web_app/templates/base.html'), 'utf8');
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];
const flush = () => new Promise(resolve => setImmediate(resolve));
const response = value => ({ ok: true, json: async () => value });
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

function harness(replies) {
  const timers = new Map();
  const storage = new Map();
  const message = { textContent: '' };
  const errorBox = { textContent: '', hidden: true };
  const button = { disabled: false, textContent: '更新', dataset: { updateLabel: '更新' } };
  let handler;
  let nextTimer = 0;
  let reloads = 0;
  const calls = [];
  const form = {
    action: '/update/run', dataset: {},
    addEventListener: (_, callback) => { handler = callback; },
    querySelectorAll: () => [button],
  };
  const panel = {
    dataset: { updateStatusUrl: '/update/status' },
    querySelector: selector => selector === '[data-update-message]' ? message
      : selector === '[data-update-error]' ? errorBox : null,
    querySelectorAll: () => [button],
  };
  const document = {
    querySelector: () => null,
    querySelectorAll: selector => selector === '[data-background-update-form]' ? [form] : [panel],
  };
  const window = {
    sessionStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    location: { reload: () => { reloads++; } },
    confirm: () => true,
    setTimeout: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
    clearTimeout: id => timers.delete(id),
  };
  const fetch = async (url, options) => {
    calls.push({ url, options });
    assert.ok(replies.length, '意外的重复请求');
    const reply = replies.shift();
    if (reply instanceof Error) throw reply;
    return reply;
  };
  vm.runInNewContext(script, { document, window, fetch });
  return {
    calls, timers, storage, message, errorBox, button,
    reloads: () => reloads,
    submit: () => handler({ preventDefault() {} }),
    tick: async () => {
      assert.equal(timers.size, 1, '只能存在一个待执行轮询');
      const [id, timer] = timers.entries().next().value;
      timers.delete(id);
      await timer.callback();
      await flush();
    },
  };
}

test('失败后持续退避，恢复后只有一个轮询', async () => {
  const ui = harness([new Error('offline'), new Error('offline'), response({ running: true }), response({ running: false, state: 'finished' })]);
  await flush();
  assert.equal([...ui.timers.values()][0].delay, 5000);
  await ui.tick();
  assert.equal([...ui.timers.values()][0].delay, 10000);
  await ui.tick();
  assert.equal([...ui.timers.values()][0].delay, 5000);
  await ui.tick();
  assert.equal([...ui.timers.values()][0].delay, 30000);
  assert.equal(ui.calls.length, 4);
  assert.equal(ui.reloads(), 0);
});

test('POST 403 清除待刷新标记并恢复按钮，不因旧任务完成刷新页面', async () => {
  const ui = harness([response({ state: 'finished', running: false }), { ok: false, status: 403, json: async () => ({ detail: 'writes disabled' }) }, response({ state: 'finished', running: false })]);
  await flush();
  await ui.submit();
  assert.equal(ui.storage.has('stock:updatePending'), false);
  assert.equal(ui.button.disabled, false);
  assert.match(ui.errorBox.textContent, /writes disabled/);
  await ui.tick();
  assert.equal(ui.reloads(), 0);
});

test('成功提交的任务结束后仅刷新一次', async () => {
  const ui = harness([response({ state: 'idle', running: false }), response({ started: true }), response({ state: 'running', running: true }), response({ state: 'finished', running: false }), response({ state: 'finished', running: false })]);
  await flush();
  await ui.submit();
  await flush();
  await ui.tick();
  assert.equal(ui.reloads(), 1);
  assert.equal(ui.storage.has('stock:updatePending'), false);
  await ui.tick();
  assert.equal(ui.reloads(), 1);
});

test('POST失败后晚到的旧状态不能覆盖页面错误', async () => {
  const oldStatus = deferred();
  const ui = harness([
    oldStatus.promise,
    { ok: false, status: 403, json: async () => ({ detail: '当前服务为只读模式，未启用写操作' }) },
  ]);
  await flush();
  await ui.submit();
  assert.match(ui.message.textContent, /更新未启动/);
  assert.match(ui.errorBox.textContent, /只读模式/);

  oldStatus.resolve(response({ state: 'finished', running: false, message: '旧任务已完成' }));
  await flush();
  await flush();

  assert.match(ui.message.textContent, /更新未启动/);
  assert.match(ui.errorBox.textContent, /只读模式/);
});
