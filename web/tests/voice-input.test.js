const assert = require('node:assert/strict');
const { VoiceTextComposer, resampleToPcm16 } = require('../voice-input.js');

const composer = new VoiceTextComposer();
composer.begin('我想在上海开店', 3, 5, 240);
assert.deepEqual(composer.preview('武汉', '开'), {
  value: '我想在武汉开开店',
  start: 6,
  end: 6,
});
assert.deepEqual(composer.final('武汉'), {
  value: '我想在武汉开店',
  start: 5,
  end: 5,
});
assert.deepEqual(composer.restore(), {
  value: '我想在上海开店',
  start: 3,
  end: 5,
});

const insertion = new VoiceTextComposer();
insertion.begin('预算万', 2, 2, 6);
assert.deepEqual(insertion.final('八十'), {
  value: '预算八十万',
  start: 4,
  end: 4,
});

const source = new Float32Array(4800).fill(0.5);
const pcm = resampleToPcm16(source, 48000, 16000);
assert.equal(pcm.byteLength, 3200);
assert.ok(new Int16Array(pcm)[0] > 16000);

console.log('voice-input tests passed');


