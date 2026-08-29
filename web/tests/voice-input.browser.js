const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const fakeBrowserApis = `
class FakeSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;
  constructor() {
    this.readyState = FakeSocket.CONNECTING;
    window.__fakeSocket = this;
    queueMicrotask(() => {
      this.readyState = FakeSocket.OPEN;
      if (this.onopen) this.onopen({});
      queueMicrotask(() => this.emit({ type: 'ready' }));
    });
  }
  emit(payload) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) });
  }
  send(payload) {
    if (typeof payload === 'string' && JSON.parse(payload).type === 'commit') {
      queueMicrotask(() => this.emit({ type: 'final', text: '武汉' }));
    }
  }
  close() {
    this.readyState = FakeSocket.CLOSED;
    if (this.onclose) this.onclose({});
  }
}
window.WebSocket = FakeSocket;
Object.defineProperty(navigator, 'mediaDevices', {
  configurable: true,
  value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) },
});
class FakeAudioNode {
  connect() { return this; }
  disconnect() {}
}
class FakeAudioContext {
  constructor() { this.sampleRate = 48000; this.destination = {}; }
  resume() { return Promise.resolve(); }
  close() { return Promise.resolve(); }
  createMediaStreamSource() { return new FakeAudioNode(); }
  createGain() { const node = new FakeAudioNode(); node.gain = { value: 1 }; return node; }
  createScriptProcessor() { const node = new FakeAudioNode(); node.onaudioprocess = null; return node; }
}
window.AudioContext = FakeAudioContext;
window.AudioWorkletNode = undefined;
`;

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  });
  const page = await browser.newPage();
  await page.addInitScript(fakeBrowserApis);
  await page.goto(process.env.TEST_URL || 'http://127.0.0.1:4173', { waitUntil: 'networkidle' });
  await page.locator('[data-route="home"]').first().click();

  const textarea = page.locator('#profile-input');
  const button = page.locator('.voice-button');
  await textarea.fill('我想在上海开店');
  await textarea.focus();
  await textarea.evaluate((node) => node.setSelectionRange(3, 5));

  await button.dispatchEvent('pointerdown', { pointerId: 1, button: 0 });
  await page.waitForFunction(() => document.querySelector('.voice-button').dataset.voiceState === 'recording');
  await page.evaluate(() => window.__fakeSocket.emit({ type: 'partial', confirmed: '武', draft: '汉' }));
  assert.equal(await textarea.inputValue(), '我想在武汉开店');

  await button.dispatchEvent('pointerup', { pointerId: 1, button: 0 });
  await page.waitForFunction(() => document.querySelector('.voice-button').dataset.voiceState === 'idle');
  assert.equal(await textarea.inputValue(), '我想在武汉开店');
  assert.deepEqual(await textarea.evaluate((node) => [node.selectionStart, node.selectionEnd]), [5, 5]);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'profile-input');

  await textarea.fill('预算写在这里');
  await textarea.focus();
  await textarea.evaluate((node) => node.setSelectionRange(2, 2));
  await button.dispatchEvent('pointerdown', { pointerId: 2, button: 0 });
  await page.waitForFunction(() => document.querySelector('.voice-button').dataset.voiceState === 'recording');
  await page.evaluate(() => window.__fakeSocket.emit({ type: 'partial', confirmed: '八万', draft: '' }));
  assert.equal(await textarea.inputValue(), '预算八万写在这里');
  await page.evaluate(() => window.__fakeSocket.emit({ type: 'error', message: '没有听清，请重试' }));
  assert.equal(await textarea.inputValue(), '预算写在这里');
  assert.deepEqual(await textarea.evaluate((node) => [node.selectionStart, node.selectionEnd]), [2, 2]);

  await browser.close();
  console.log('voice input browser test passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});


