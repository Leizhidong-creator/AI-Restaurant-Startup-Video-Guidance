(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.PocketMentorVoiceInput = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  class VoiceTextComposer {
    begin(value, selectionStart, selectionEnd, maxLength) {
      const text = String(value || '');
      const start = Math.max(0, Math.min(Number.isInteger(selectionStart) ? selectionStart : text.length, text.length));
      const end = Math.max(start, Math.min(Number.isInteger(selectionEnd) ? selectionEnd : start, text.length));
      this.anchor = {
        original: text,
        prefix: text.slice(0, start),
        suffix: text.slice(end),
        start,
        end,
        maxLength: Number.isInteger(maxLength) && maxLength > 0 ? maxLength : Infinity,
      };
      return this.anchor;
    }

    preview(confirmed, draft) {
      return this._compose(String(confirmed || '') + String(draft || ''));
    }

    final(transcript) {
      return this._compose(String(transcript || ''));
    }

    restore() {
      if (!this.anchor) return { value: '', start: 0, end: 0 };
      return {
        value: this.anchor.original,
        start: this.anchor.start,
        end: this.anchor.end,
      };
    }

    _compose(insertion) {
      if (!this.anchor) throw new Error('VoiceTextComposer.begin() must be called first');
      const room = Math.max(0, this.anchor.maxLength - this.anchor.prefix.length - this.anchor.suffix.length);
      const inserted = insertion.slice(0, room);
      const caret = this.anchor.prefix.length + inserted.length;
      return {
        value: this.anchor.prefix + inserted + this.anchor.suffix,
        start: caret,
        end: caret,
      };
    }
  }

  function resampleToPcm16(input, inputRate, outputRate) {
    const targetRate = outputRate || 16000;
    if (!input || !input.length || !inputRate) return new ArrayBuffer(0);
    const ratio = inputRate / targetRate;
    const outputLength = Math.max(1, Math.floor(input.length / ratio));
    const pcm = new Int16Array(outputLength);
    for (let i = 0; i < outputLength; i += 1) {
      const sourceIndex = i * ratio;
      const lower = Math.floor(sourceIndex);
      const upper = Math.min(lower + 1, input.length - 1);
      const mix = sourceIndex - lower;
      const sample = Math.max(-1, Math.min(1, input[lower] * (1 - mix) + input[upper] * mix));
      pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    }
    return pcm.buffer;
  }

  class VoiceInputController {
    constructor(options) {
      this.textarea = options.textarea;
      this.button = options.button;
      this.status = options.status;
      this.websocketUrl = options.websocketUrl;
      this.workletUrl = options.workletUrl || './pcm-capture-worklet.js';
      this.composer = new VoiceTextComposer();
      this.state = 'idle';
      this.pointerDown = false;
      this.retryCount = 0;
      this.cachedFrames = [];
      this.hasFinal = false;
      this.intentionalClose = false;
      this.socketReady = false;
      this.gestureId = 0;
      this.statusTimer = null;
      this.maxTimer = null;
      this._bind();
    }

    _bind() {
      this.button.addEventListener('pointerdown', (event) => this._onPointerDown(event));
      this.button.addEventListener('pointerup', (event) => this._onPointerUp(event));
      this.button.addEventListener('pointercancel', () => this.cancel());
      this.button.addEventListener('contextmenu', (event) => event.preventDefault());
      this.button.addEventListener('keydown', (event) => {
        if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) this._onPointerDown(event);
      });
      this.button.addEventListener('keyup', (event) => {
        if (event.key === ' ' || event.key === 'Enter') this._onPointerUp(event);
      });
      document.addEventListener('visibilitychange', () => {
        if (document.hidden && this.state !== 'idle') this.cancel();
      });
      window.addEventListener('pagehide', () => this.cancel());
    }

    _onPointerDown(event) {
      if (!['idle', 'error'].includes(this.state)) return;
      event.preventDefault();
      if (event.pointerId !== undefined && this.button.setPointerCapture) {
        try { this.button.setPointerCapture(event.pointerId); } catch (_error) { /* no-op */ }
      }
      const value = this.textarea.value;
      this.composer.begin(
        value,
        this.textarea.selectionStart,
        this.textarea.selectionEnd,
        this.textarea.maxLength
      );
      this.pointerDown = true;
      this.retryCount = 0;
      this.cachedFrames = [];
      this.hasFinal = false;
      this.intentionalClose = false;
      const gestureId = ++this.gestureId;
      this._startGesture(gestureId);
    }

    _onPointerUp(event) {
      event.preventDefault();
      this.pointerDown = false;
      if (event.pointerId !== undefined && this.button.releasePointerCapture) {
        try { this.button.releasePointerCapture(event.pointerId); } catch (_error) { /* no-op */ }
      }
      if (this.state === 'recording') this.finish();
    }

    async _startGesture(gestureId) {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        this._fail('当前浏览器不支持语音输入');
        return;
      }
      this._setState('requesting_permission', '正在请求麦克风权限…');
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        });
      } catch (_error) {
        if (gestureId === this.gestureId) this._fail('无法使用麦克风，请在浏览器设置中允许权限');
        return;
      }

      if (gestureId !== this.gestureId || !this.pointerDown) {
        this._stopMedia();
        this._restoreAnchor();
        this._setState('idle', '麦克风已准备好，请再次长按说话', true);
        return;
      }

      this._setState('connecting', '正在连接语音识别…');
      try {
        await this._openSocket(false, gestureId);
        if (gestureId !== this.gestureId || !this.pointerDown) {
          this.cancel('请重新长按后说话');
          return;
        }
        await this._startAudioCapture();
        if (gestureId !== this.gestureId || !this.pointerDown) {
          this.cancel('请重新长按后说话');
          return;
        }
        this._setState('recording', '正在听，松开发送');
        this.maxTimer = setTimeout(() => {
          this.pointerDown = false;
          this.finish();
        }, 60000);
      } catch (_error) {
        if (gestureId === this.gestureId && this.state !== 'idle') this._fail('语音识别连接失败，请重试');
      }
    }

    _openSocket(isRetry, gestureId) {
      return new Promise((resolve, reject) => {
        const socket = new WebSocket(this.websocketUrl);
        socket.binaryType = 'arraybuffer';
        this.socket = socket;
        this.socketReady = false;
        let ready = false;
        const timeout = setTimeout(() => {
          if (!ready) {
            this.intentionalClose = true;
            socket.close();
            reject(new Error('WebSocket timeout'));
          }
        }, 12000);

        socket.onmessage = (message) => {
          let event;
          try { event = JSON.parse(message.data); } catch (_error) { return; }
          if (event.type === 'ready') {
            ready = true;
            clearTimeout(timeout);
            if (isRetry) this.cachedFrames.forEach((frame) => socket.send(frame));
            this.socketReady = true;
            resolve();
          } else if (event.type === 'partial' && gestureId === this.gestureId) {
            this._applyComposition(this.composer.preview(event.confirmed, event.draft));
          } else if (event.type === 'final' && gestureId === this.gestureId) {
            this._handleFinal(event.text);
          } else if (event.type === 'error' && gestureId === this.gestureId) {
            this._fail(event.message || '没有听清，请重试');
          } else if (event.type === 'closed' && !this.hasFinal && gestureId === this.gestureId) {
            this._fail('没有听清，请重试');
          }
        };
        socket.onerror = () => {
          if (!ready) {
            clearTimeout(timeout);
            reject(new Error('WebSocket error'));
          }
        };
        socket.onclose = () => {
          clearTimeout(timeout);
          this.socketReady = false;
          if (!ready) reject(new Error('WebSocket closed'));
          else if (!this.intentionalClose && !this.hasFinal && gestureId === this.gestureId) {
            this._recoverSocket(gestureId);
          }
        };
      });
    }

    async _recoverSocket(gestureId) {
      if (!['recording', 'finalizing'].includes(this.state)) return;
      if (this.retryCount >= 1) {
        this._fail('网络中断，原文字已保留');
        return;
      }
      this.retryCount += 1;
      const shouldCommit = this.state === 'finalizing';
      this._setState('connecting', '网络波动，正在重连…');
      try {
        await this._openSocket(true, gestureId);
        if (gestureId !== this.gestureId) return;
        if (shouldCommit || !this.pointerDown) {
          this._setState('finalizing', '正在转成文字…');
          this.socket.send(JSON.stringify({ type: 'commit' }));
        } else {
          this._setState('recording', '正在听，松开发送');
        }
      } catch (_error) {
        this._fail('网络中断，原文字已保留');
      }
    }

    async _startAudioCapture() {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) throw new Error('AudioContext unavailable');
      this.audioContext = new AudioContext();
      await this.audioContext.resume();
      this.audioSource = this.audioContext.createMediaStreamSource(this.stream);
      this.silentGain = this.audioContext.createGain();
      this.silentGain.gain.value = 0;

      if (this.audioContext.audioWorklet && window.AudioWorkletNode) {
        try {
          await this.audioContext.audioWorklet.addModule(this.workletUrl);
          this.audioNode = new AudioWorkletNode(this.audioContext, 'pcm-capture-processor');
          this.audioNode.port.onmessage = (event) => this._pushAudio(event.data);
          this.audioSource.connect(this.audioNode);
          this.audioNode.connect(this.silentGain);
          this.silentGain.connect(this.audioContext.destination);
          return;
        } catch (_error) {
          if (this.audioNode) this.audioNode.disconnect();
        }
      }

      const processor = this.audioContext.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = (event) => {
        this._pushAudio(new Float32Array(event.inputBuffer.getChannelData(0)));
      };
      this.audioNode = processor;
      this.audioSource.connect(processor);
      processor.connect(this.silentGain);
      this.silentGain.connect(this.audioContext.destination);
    }

    _pushAudio(floatSamples) {
      if (!['recording', 'connecting'].includes(this.state) || !this.audioContext) return;
      const frame = resampleToPcm16(floatSamples, this.audioContext.sampleRate, 16000);
      if (!frame.byteLength) return;
      this.cachedFrames.push(frame);
      if (this.socketReady && this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(frame);
      }
    }

    finish() {
      if (this.state !== 'recording') return;
      clearTimeout(this.maxTimer);
      this._stopMedia();
      this._setState('finalizing', '正在转成文字…');
      if (this.socketReady && this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: 'commit' }));
      }
    }

    cancel(message) {
      if (this.state === 'idle') return;
      this.pointerDown = false;
      this.gestureId += 1;
      this.intentionalClose = true;
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: 'cancel' }));
        this.socket.close();
      }
      this._restoreAnchor();
      this._cleanup();
      this._setState('idle', message || '', Boolean(message));
    }

    _handleFinal(text) {
      if (!text) {
        this._fail('没有听清，请重试');
        return;
      }
      this.hasFinal = true;
      this._applyComposition(this.composer.final(text), true);
      this.intentionalClose = true;
      if (this.socket && this.socket.readyState === WebSocket.OPEN) this.socket.close();
      this._cleanup();
      this._setState('idle', '已转成文字', true);
    }

    _fail(message) {
      this.pointerDown = false;
      this.gestureId += 1;
      this.intentionalClose = true;
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: 'cancel' }));
        this.socket.close();
      }
      this._restoreAnchor();
      this._cleanup();
      this._setState('error', message, true);
    }

    _applyComposition(composition, focus) {
      this.textarea.value = composition.value;
      this.textarea.setSelectionRange(composition.start, composition.end);
      this.textarea.dispatchEvent(new Event('input', { bubbles: true }));
      if (focus) {
        this.textarea.focus({ preventScroll: true });
        this.textarea.setSelectionRange(composition.start, composition.end);
      }
    }

    _restoreAnchor() {
      if (!this.composer.anchor) return;
      this._applyComposition(this.composer.restore(), true);
    }

    _cleanup() {
      clearTimeout(this.maxTimer);
      this._stopMedia();
      this.cachedFrames = [];
      this.socket = null;
      this.socketReady = false;
    }

    _stopAudioGraph() {
      if (this.audioNode) {
        if ('onaudioprocess' in this.audioNode) this.audioNode.onaudioprocess = null;
        if (this.audioNode.port) this.audioNode.port.onmessage = null;
        try { this.audioNode.disconnect(); } catch (_error) { /* no-op */ }
      }
      if (this.audioSource) {
        try { this.audioSource.disconnect(); } catch (_error) { /* no-op */ }
      }
      if (this.silentGain) {
        try { this.silentGain.disconnect(); } catch (_error) { /* no-op */ }
      }
      if (this.audioContext) this.audioContext.close().catch(() => {});
      this.audioNode = null;
      this.audioSource = null;
      this.silentGain = null;
      this.audioContext = null;
    }

    _stopMedia() {
      this._stopAudioGraph();
      if (this.stream) this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }

    _setState(next, message, autoHide) {
      this.state = next;
      this.button.dataset.voiceState = next;
      this.button.classList.toggle('is-recording', next === 'recording');
      this.button.classList.toggle('is-busy', ['requesting_permission', 'connecting', 'finalizing'].includes(next));
      this.button.setAttribute('aria-pressed', String(next === 'recording'));
      const labels = {
        idle: '长按语音输入',
        requesting_permission: '正在请求麦克风权限',
        connecting: '正在连接语音识别',
        recording: '正在录音，松开发送',
        finalizing: '正在转成文字',
        error: '语音输入失败，长按重试',
      };
      this.button.setAttribute('aria-label', labels[next] || '长按语音输入');
      this.button.title = labels[next] || '长按语音输入';
      clearTimeout(this.statusTimer);
      this.status.textContent = message || '';
      this.status.hidden = !message;
      this.status.classList.toggle('is-error', next === 'error');
      if (autoHide && message) {
        this.statusTimer = setTimeout(() => {
          this.status.hidden = true;
          if (this.state === 'error') this._setState('idle', '');
        }, 2800);
      }
    }
  }

  return { VoiceInputController, VoiceTextComposer, resampleToPcm16 };
});


