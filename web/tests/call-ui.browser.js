const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const fakeRealtimeEnvironment = `
class FakeTrack {
  constructor(kind, device) { this.kind = kind; this.device = device; this.enabled = true; this.stopped = false; }
  stop() { this.stopped = true; }
}
class FakeStream {
  constructor(includeAudio = true, device = 'environment') {
    this.tracks = includeAudio ? [new FakeTrack('audio', 'mic'), new FakeTrack('video', device)] : [new FakeTrack('video', device)];
    if (includeAudio) window.__firstVideo = this.getVideoTracks()[0];
    window.__streams.push(this);
  }
  getTracks() { return this.tracks; }
  getAudioTracks() { return this.tracks.filter((track) => track.kind === 'audio'); }
  getVideoTracks() { return this.tracks.filter((track) => track.kind === 'video'); }
  addTrack(track) { this.tracks.push(track); }
  removeTrack(track) { this.tracks = this.tracks.filter((item) => item !== track); }
}
window.__streams = [];
Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', {
  configurable: true,
  get() { return this.__fakeStream || null; },
  set(value) { this.__fakeStream = value; },
});
HTMLMediaElement.prototype.play = () => Promise.resolve();
Object.defineProperty(navigator, 'mediaDevices', {
  configurable: true,
  value: {
    getUserMedia: async (constraints) => new FakeStream(Boolean(constraints.audio), constraints.video?.facingMode?.ideal || 'environment'),
  },
});
class FakeDataChannel {
  constructor() { this.readyState = 'open'; queueMicrotask(() => this.onopen && this.onopen()); }
  send() {}
  close() { this.readyState = 'closed'; }
}
window.__offerCount = 0;
window.__senders = [];
class FakePeerConnection {
  constructor() { this.senders = []; window.__peers = (window.__peers || 0) + 1; }
  addTrack(track) {
    const sender = { track, replaceTrack: async (next) => { sender.track = next; } };
    this.senders.push(sender); window.__senders.push(sender); return sender;
  }
  getSenders() { return this.senders; }
  createDataChannel() { return new FakeDataChannel(); }
  async createOffer() { window.__offerCount += 1; return { sdp: 'fake-offer' }; }
  async setLocalDescription() {}
  async setRemoteDescription() {}
  close() { this.closed = true; }
}
window.RTCPeerConnection = FakePeerConnection;
window.fetch = async (rawUrl, options = {}) => {
  const path = new URL(String(rawUrl), location.origin).pathname;
  const json = (body) => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
  if (path.endsWith('/users')) return json({ id: 'user-1' });
  if (path.endsWith('/stores')) return json({ id: 'store-1' });
  if (path.endsWith('/sessions')) return json({ id: 'session-1' });
  if (path.includes('/realtime/config/')) return json({ sdp_endpoint: '/api/v1/realtime/sdp?session_id=session-1', session_update: { type: 'session.update', session: {} } });
  if (path.includes('/realtime/sdp')) return new Response('fake-answer', { headers: { 'content-type': 'application/sdp' } });
  if (path.includes('/events')) return json({ ok: true });
  return json({ ok: true });
};
`;

const deadline = setTimeout(() => {
  console.error('call UI browser test timed out');
  process.exit(1);
}, 20000);

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  });
  const page = await browser.newPage({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 1 });
  await page.addInitScript(fakeRealtimeEnvironment);
  await page.goto(process.env.TEST_URL || 'http://127.0.0.1:4173', { waitUntil: 'networkidle' });
  await page.locator('[data-route="home"]').first().click();
  await page.locator('#profile-form').evaluate((form) => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  await page.waitForTimeout(50);
  await page.evaluate(() => document.querySelector('[data-route="call"]').click());
  await page.locator('#live-consent-start').click();
  await page.waitForFunction(() => document.querySelector('#call-status-text').textContent === '已连接');

  assert.equal(await page.locator('.mentor-float').count(), 0);
  assert.equal(await page.locator('.observation-tag').count(), 0);
  assert.equal(await page.locator('#local-video').evaluate((node) => getComputedStyle(node).transform), 'none');
  assert.equal(await page.locator('.call-status').evaluate((node) => getComputedStyle(node).display), 'flex');
  assert.ok(await page.locator('.call-controls .control-icon').first().evaluate((node) => node.getBoundingClientRect().width <= 44));

  await page.locator('#guide-text').evaluate((node) => { node.textContent = '这是一段足够长的字幕文本，用于验证字幕容器会随着文字自然增高，而不会把顶部内容裁切掉。'; });
  assert.equal(await page.locator('.guide-caption').evaluate((node) => node.scrollHeight === node.clientHeight), true);

  await page.locator('#mute-control').click();
  assert.equal(await page.locator('#mute-control').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('#mute-control small').textContent(), '开声音');
  assert.equal(await page.evaluate(() => window.__streams[0].getAudioTracks()[0].enabled), false);

  await page.locator('#camera-control').click();
  await page.waitForFunction(() => window.__streams.length === 2);
  assert.equal(await page.evaluate(() => window.__firstVideo.stopped), true);
  assert.equal(await page.evaluate(() => window.__senders.find((sender) => sender.track.kind === 'video').track.device), 'user');

  await page.locator('#reconnect-control').click();
  await page.waitForFunction(() => window.__offerCount === 2);
  await page.waitForFunction(() => document.querySelector('#call-status-text').textContent === '已连接');
  assert.equal(await page.locator('#call-status-text').textContent(), '已连接');

  await page.screenshot({ path: '/tmp/pocketmentor-call-ui.png' });
  await browser.close();
  clearTimeout(deadline);
  console.log('call UI browser test passed');
})().catch((error) => {
  clearTimeout(deadline);
  console.error(error);
  process.exitCode = 1;
});


