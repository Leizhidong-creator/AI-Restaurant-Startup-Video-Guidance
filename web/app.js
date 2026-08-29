(function () {
  'use strict';

  // ── 真实后端接线 ───────────────────────────────────────────
  // 第一刀:建档(创建 user + store)走雷后端真实接口。
  // 其余流程(上传/解构/连麦/复盘)暂仍 demo,后续逐刀替换。
  // 开发预览固定在 5173: 本机和同一局域网的手机都请求这台机器的 8010 后端。
  // 正式部署不走这个分支，仍使用同源 API。
  const isLocalDevelopment = location.port === '5173';
  const API_ORIGIN = window.POCKETMENTOR_API_ORIGIN ||
    (isLocalDevelopment ? `${location.protocol}//${location.hostname}:8010` : location.origin);
  const API_BASE = API_ORIGIN + '/api/v1';
  const ASR_WEBSOCKET_URL = API_ORIGIN.replace(/^http/, 'ws') + '/api/v1/asr/stream';
  async function apiPost(path, body) {
    const res = await fetch(API_BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  }
  async function apiPatch(path, body) {
    const res = await fetch(API_BASE + path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  }
  async function apiUpload(path, file) {
    const fd = new FormData();
    fd.append('file', file, file.name || 'video.mp4');
    const res = await fetch(API_BASE + path, { method: 'POST', body: fd });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  }
  const escHtml = (t) => String(t == null ? '' : t).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const fmtMs = (ms) => {
    if (ms == null) return '';
    const s = Math.round(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  };

  const state = {
    screen: 'welcome',
    history: [],
    profile: '我 24 岁，想在武汉开奶茶店，预算 8 万，以前没开过店。',
    userId: null,
    storeId: null,
    video: null,
    analysis: null,
    videoMeta: null,
    demoMode: false,
    stream: null,
    peer: null,
    muted: false,
    camera: true,
    elapsed: 0,
    timer: null,
    guideIndex: 0,
    callEvents: []
  };

  const screens = [...document.querySelectorAll('[data-screen]')];
  const app = document.querySelector('#app');
  const hostBack = document.querySelector('#host-back');
  const consultationMenu = document.querySelector('#consultation-menu');
  const consultationClose = document.querySelector('#consultation-close');
  const consultationSheetLayer = document.querySelector('#consultation-sheet-layer');
  const exitConsultationLayer = document.querySelector('#exit-consultation-layer');
  const hostMessage = document.querySelector('#host-message');

  const voiceInput = new window.PocketMentorVoiceInput.VoiceInputController({
    textarea: document.querySelector('#profile-input'),
    button: document.querySelector('.voice-button'),
    status: document.querySelector('#voice-input-status'),
    websocketUrl: ASR_WEBSOCKET_URL,
    workletUrl: './pcm-capture-worklet.js',
  });

  const screenLabels = {
    welcome: '从一句话和一条案例视频开始。',
    upload: '第 1 步：上传你刷到的成功案例。',
    home: '第 2 步：说说你想开的店。',
    call: '第 4 步：连麦看你的真实现场。',
    'recap-loading': '正在整理现场观察和建议。',
    recap: '第 5 步：查看适合你的下一步。',
  };

  const showHostMessage = (message) => {
    clearTimeout(showHostMessage.timer);
    hostMessage.textContent = message;
    hostMessage.hidden = false;
    showHostMessage.timer = setTimeout(() => { hostMessage.hidden = true; }, 2600);
  };

  const syncHostNavigation = () => {
    const consentOpen = !document.querySelector('#live-consent-modal').hidden;
    const locked = state.screen === 'recap-loading' || (state.screen === 'call' && !consentOpen);
    hostBack.disabled = state.history.length === 0 || locked;
    hostBack.title = locked ? '请先结束当前连麦' : state.history.length ? '返回上一步' : '已经在咨询起点';
    consultationMenu.disabled = locked;
    consultationClose.disabled = locked;
  };

  const showScreen = (next) => {
    state.screen = next;
    screens.forEach((screen) => screen.classList.toggle('active', screen.dataset.screen === next));
    const scrollTarget = document.querySelector('.app-shell');
    if (scrollTarget && scrollTarget.scrollHeight > scrollTarget.clientHeight) scrollTarget.scrollTo({ top: 0, behavior: 'smooth' });
    else window.scrollTo({ top: 0, behavior: 'smooth' });
    app.focus({ preventScroll: true });
    if (next === 'upload') renderHistory();
    syncHostNavigation();
  };

  const route = (next, replace) => {
    if (!replace && state.screen !== next) state.history.push(state.screen);
    showScreen(next);
  };

  const goBack = () => {
    if (state.screen === 'call' && !liveConsentModal.hidden) {
      liveConsentModal.hidden = true;
      showScreen(state.history.pop() || 'upload');
      return;
    }
    if (state.screen === 'call' || state.screen === 'recap-loading') {
      showHostMessage('请先完成或结束当前连麦。');
      return;
    }
    const previous = state.history.pop();
    if (!previous) {
      showHostMessage('已经在咨询起点。');
      return;
    }
    showScreen(previous);
  };

  const setConsultationSheet = (open) => {
    consultationSheetLayer.hidden = !open;
    consultationMenu.setAttribute('aria-expanded', String(open));
    if (open) document.querySelector('#consultation-sheet-status').textContent = screenLabels[state.screen] || '继续完成这次咨询。';
  };

  const resetConsultation = () => {
    // 只重置前端本次演示状态；不删除已经创建的后端会话与报告。
    state.history = [];
    state.profile = '我 24 岁，想在武汉开奶茶店，预算 8 万，以前没开过店。';
    state.userId = null;
    state.storeId = null;
    state.video = null;
    state.videoMeta = null;
    state.analysis = null;
    state.deconstruction = null;
    state.deconstructPending = false;
    state.analysisPending = false;
    state.profileDone = false;
    state.pendingDeconstructId = null;
    document.querySelector('#profile-input').value = state.profile;
    document.querySelector('#upload-progress').hidden = true;
    document.querySelector('#video-source').hidden = false;
    document.querySelector('.demo-case-placeholder').hidden = false;
    document.querySelector('#video-input').value = '';
    document.querySelector('#video-url').value = '';
    document.querySelector('#video-url-error').hidden = true;
    document.querySelector('#link-relevance-modal').hidden = true;
    document.querySelector('#enter-call').hidden = true;
    updateProfileSummary();
    setConsultationSheet(false);
    exitConsultationLayer.hidden = true;
    showScreen('welcome');
  };

  hostBack.addEventListener('click', goBack);
  consultationMenu.addEventListener('click', () => {
    if (!consultationMenu.disabled) setConsultationSheet(consultationSheetLayer.hidden);
  });
  document.querySelector('#dismiss-consultation-sheet').addEventListener('click', () => setConsultationSheet(false));
  document.querySelector('#restart-consultation').addEventListener('click', resetConsultation);
  consultationClose.addEventListener('click', () => {
    if (consultationClose.disabled) return;
    if (state.screen === 'welcome') { showHostMessage('已经在咨询首页。'); return; }
    setConsultationSheet(false);
    exitConsultationLayer.hidden = false;
  });
  document.querySelector('#cancel-exit-consultation').addEventListener('click', () => { exitConsultationLayer.hidden = true; });
  document.querySelector('#confirm-exit-consultation').addEventListener('click', resetConsultation);
  [consultationSheetLayer, exitConsultationLayer].forEach((layer) => layer.addEventListener('click', (event) => {
    if (event.target === layer) {
      layer.hidden = true;
      consultationMenu.setAttribute('aria-expanded', 'false');
    }
  }));

  document.addEventListener('click', (event) => {
    const target = event.target.closest('[data-route]');
    if (!target) return;
    if (target.dataset.route === 'call') { openLiveConsent(); return; }
    route(target.dataset.route);
  });

  const liveConsentModal = document.querySelector('#live-consent-modal');
  const liveConsentError = document.querySelector('#live-consent-error');
  // 确认弹窗已移除:隐私说明前移到加载页按钮下方,点击即直接开始连麦
  const openLiveConsent = () => { startCall(false); };
  document.querySelector('#enter-call').addEventListener('click', () => openLiveConsent());
  document.querySelector('#live-consent-start').addEventListener('click', () => startCall(false));
  document.querySelector('#live-consent-cancel').addEventListener('click', () => {
    liveConsentModal.hidden = true;
    route('upload', true);
  });

  const parseProfile = (text) => {
    const city = (text.match(/(武汉|上海|北京|广州|深圳|杭州|成都|重庆)/) || [])[1] || '你的城市';
    const category = (text.match(/(奶茶|咖啡|面馆|小吃|烘焙|火锅|餐饮)/) || [])[1] || '餐饮店';
    const budget = (text.match(/预算[^，。；;]{0,10}/) || [])[0] || '预算待确认';
    const experience = /没开过|没有经验|新手|第一次/.test(text) ? '暂无经验' : '已有经营经验';
    return { city, category, budget, experience };
  };
  const updateProfileSummary = () => {
    const p = parseProfile(state.profile);
    const summaryEl = document.querySelector('#profile-summary');
    if (summaryEl) summaryEl.textContent = `${p.city} · ${p.category} · ${p.budget.replace('预算', '预算')} · ${p.experience}`;
  };

  // 视频先行:进入上传流程前保证有占位档(用户情况随后在建档页补充)
  async function ensureDraftProfile() {
    if (state.storeId) return;
    const user = await apiPost('/users', { display_name: '口袋餐谋用户' });
    const store = await apiPost(`/users/${user.id}/stores`, {
      name: '想法待补充', category: '餐饮', stage: 'planning',
    });
    state.userId = user.id;
    state.storeId = store.id;
  }

  document.querySelector('#profile-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    state.profile = document.querySelector('#profile-input').value.trim();
    if (!state.profile) return;
    updateProfileSummary();
    const submitBtn = event.target.querySelector('[type="submit"]');
    const restore = submitBtn ? submitBtn.textContent : '';
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = '正在建档…'; }
    try {
      // 门店名用用户原话(逐字);品类取拼装器选择,便于迁移初判按品类下判断
      const category = (ideaSelection.category || '餐饮').replace(/店$/, '') || '餐饮';
      if (state.storeId) {
        await apiPatch(`/stores/${state.storeId}`, { name: state.profile.slice(0, 60), category });
      } else {
        const user = await apiPost('/users', { display_name: '口袋餐谋用户' });
        const store = await apiPost(`/users/${user.id}/stores`, {
          name: state.profile.slice(0, 60), category, stage: 'planning',
        });
        state.userId = user.id;
        state.storeId = store.id;
      }
      state.profileDone = true;
      // 视频已解析、解构在等品类 → 现在补跑
      if (state.pendingDeconstructId) { runDeconstruct(state.pendingDeconstructId); state.pendingDeconstructId = null; }
      route('upload', true); // 回到就绪页(进度面板 + 进入连麦按钮)
    } catch (err) {
      window.alert('建档失败，请检查网络后重试：\n' + err.message);
    } finally {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = restore; }
    }
  });
  // 想法拼装器:各组点选组合成一句完整想法,填进输入框(用户仍可手改)
  const ideaSelection = { category: '奶茶店', place: '商圈', budget: '8 万', experience: '没开过店' };
  const composeIdea = () => {
    const exp = { '没开过店': '以前没开过店', '开过一家店': '之前开过一家店', '在餐饮行业干过': '在餐饮行业干过' }[ideaSelection.experience];
    document.querySelector('#profile-input').value =
      `我想在${ideaSelection.place}开一家${ideaSelection.category}，预算 ${ideaSelection.budget}，${exp}。`;
  };
  document.querySelectorAll('#idea-builder .idea-options').forEach((group) => {
    group.addEventListener('click', (event) => {
      const btn = event.target.closest('button[data-value]');
      if (!btn) return;
      ideaSelection[group.dataset.field] = btn.dataset.value;
      ideaSelection._touched = ideaSelection._touched || {};
      ideaSelection._touched[group.dataset.field] = true;
      group.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b === btn)));
      composeIdea();
    });
  });
  const videoInput = document.querySelector('#video-input');
  const videoUrl = document.querySelector('#video-url');
  const videoUrlError = document.querySelector('#video-url-error');
  const videoSource = document.querySelector('#video-source');
  const parseVideoUrlButton = document.querySelector('#parse-video-url');
  const linkRelevanceModal = document.querySelector('#link-relevance-modal');
  let pendingLinkText = '';
  document.querySelector('#upload-trigger').addEventListener('click', () => videoInput.click());
  videoInput.addEventListener('change', () => { if (videoInput.files[0]) uploadAndAnalyze(videoInput.files[0]); });
  parseVideoUrlButton.addEventListener('click', async () => {
    const value = videoUrl.value.trim();
    // 分享文案常混杂表情和口令,只要包含 http(s) 链接就交给后端提取并下载(真实 yt-dlp 流程)
    if (!/https?:\/\//.test(value)) {
      videoUrlError.textContent = '请粘贴包含视频链接的分享内容。';
      videoUrlError.hidden = false;
      return;
    }
    videoUrlError.hidden = true;
    parseVideoUrlButton.disabled = true;
    parseVideoUrlButton.textContent = '识别中…';
    try {
      const preview = await apiPost(`/stores/${state.storeId}/videos/from-url/preview`, { url: value });
      if (preview.relevance === 'low') {
        pendingLinkText = value;
        document.querySelector('#link-preview-title-text').textContent = preview.title || '未识别到视频标题';
        document.querySelector('#link-relevance-reason').textContent = preview.reason || '标题与餐饮经营的关联较弱。';
        linkRelevanceModal.hidden = false;
        document.querySelector('#continue-low-relevance').focus();
      } else {
        await ingestUrlAndAnalyze(value);
      }
    } catch (err) {
      videoUrlError.textContent = '暂时无法读取这条视频的信息，请检查链接后重试。';
      videoUrlError.hidden = false;
      console.warn('[链接预检失败]', err.message);
    } finally {
      parseVideoUrlButton.disabled = false;
      parseVideoUrlButton.textContent = '解析';
    }
  });
  document.querySelector('#continue-low-relevance').addEventListener('click', () => {
    const value = pendingLinkText;
    pendingLinkText = '';
    linkRelevanceModal.hidden = true;
    if (value) ingestUrlAndAnalyze(value);
  });
  document.querySelector('#replace-low-relevance').addEventListener('click', () => {
    pendingLinkText = '';
    linkRelevanceModal.hidden = true;
    videoUrl.focus();
    videoUrl.select();
  });
  document.querySelector('#cancel-upload').addEventListener('click', () => {
    document.querySelector('#upload-progress').hidden = true;
    videoSource.hidden = false;
    document.querySelector('.demo-case-placeholder').hidden = false;
    videoInput.value = '';
    videoUrl.value = '';
    videoUrlError.hidden = true;
  });

  // 获取(上传或链接取回)→ Qwen 解析 → 四维解构 → 进解析页;链接与上传共用同一条真实进度条
  async function acquireAndAnalyze(displayName, initialMeta, acquire) {
    try { await ensureDraftProfile(); } catch (err) { window.alert('连接服务失败，请稍后重试：\n' + err.message); return; }
    videoSource.hidden = true;
    document.querySelector('.demo-case-placeholder').hidden = true;
    document.querySelector('#upload-progress').hidden = false;
    document.querySelector('#file-name').textContent = displayName;
    document.querySelector('#file-meta').textContent = initialMeta;
    const bar = document.querySelector('#progress-bar');
    const steps = [...document.querySelectorAll('[data-process]')];
    steps.forEach((s) => s.classList.remove('done'));
    let progress = 8; bar.style.width = '8%';
    // 获取+解析是真实网络调用(Qwen 解析约 20–40 秒,链接还要先下载),进度条缓慢爬升表示"进行中"
    const creep = setInterval(() => {
      progress = Math.min(progress + 3, 92);
      bar.style.width = `${progress}%`;
      steps.forEach((item, index) => { if (progress >= (index + 1) * 28) item.classList.add('done'); });
    }, 900);
    try {
      const uploaded = await acquire();
      clearInterval(creep);
      // 渐进式披露:视频到手即可进入下一步,解析/解构转后台;连麦不必等分析产出,
      // 后台每出一批成果就注入正在进行的通话(见 injectCaseIntoCall)。
      state.videoMeta = uploaded;
      state.analysis = null; state.analysisPending = true;
      state.deconstruction = null; state.deconstructPending = true;
      document.querySelector('#file-name').textContent = uploaded.filename || displayName;
      bar.style.width = '100%'; steps.forEach((s) => s.classList.add('done'));
      document.querySelector('#file-meta').textContent = '视频已就绪 · AI 正在细看（可直接连麦）';
      backgroundAnalyze(uploaded.id);
      document.querySelector('#enter-call').hidden = false;
      if (!state.profileDone) {
        // 视频先行流程:拿到视频就去补充"你的情况",回来时就绪页已在等你
        setTimeout(() => route('home'), 600);
      }
    } catch (err) {
      clearInterval(creep);
      document.querySelector('#file-meta').textContent = '获取失败';
      window.alert('获取视频失败:\n' + err.message);
      document.querySelector('#upload-progress').hidden = true;
      videoSource.hidden = false;
      document.querySelector('.demo-case-placeholder').hidden = false;
    }
  }

  // 后台解析链:Qwen 整段解析 → 四维解构;每个阶段完成即更新页面并注入进行中的通话
  function backgroundAnalyze(videoId) {
    apiPost(`/videos/${videoId}/analyze`)
      .then((analyzed) => {
        if (analyzed.status !== 'completed') throw new Error(analyzed.error_message || `解析状态 ${analyzed.status}`);
        state.videoMeta = analyzed;
        state.analysis = analyzed.analysis_json || null;
        state.analysisPending = false;
        injectCaseIntoCall('analysis');
        suggestCategoryFromCase();
        if (state.profileDone) {
          document.querySelector('#file-meta').textContent = '案例已解析 · 正在做四维判断…';
          runDeconstruct(videoId);
        } else {
          // 迁移初判依赖你的品类:等建档完成再跑,避免张冠李戴
          state.pendingDeconstructId = videoId;
          document.querySelector('#file-meta').textContent = '案例已解析 · 说说你的情况后出四维判断';
        }
      })
      .catch((err) => {
        console.warn('[后台解析失败]', err.message);
        state.analysisPending = false; state.deconstructPending = false;
        document.querySelector('#file-meta').textContent = '深度分析未完成 · 可直接连麦口头描述案例';
      });
  }

  // 从案例解析文本里识别品类,给建档页对应选项打"视频同款"标(推荐不强制,选项全保留)
  const CASE_CATEGORY_KEYWORDS = [
    ['奶茶店', /奶茶|茶饮|果茶/], ['咖啡店', /咖啡/], ['烧烤店', /烧烤|烤串|串串/],
    ['火锅店', /火锅/], ['烘焙店', /烘焙|面包|蛋糕|甜品/], ['面馆', /面馆|拉面|米线|米粉|面条/],
    ['小吃店', /小吃|炸串|卤味|煎饼/], ['家常菜馆', /餐厅|饭店|酒馆|正餐|炒菜|大排档/],
  ];
  function suggestCategoryFromCase() {
    if (!state.analysis) return;
    const corpus = (state.analysis.summary || '') + (state.analysis.claims || []).map((c) => c.content).join('');
    const hit = CASE_CATEGORY_KEYWORDS.find(([, re]) => re.test(corpus));
    if (!hit) return;
    const group = document.querySelector('[data-field="category"]');
    const btn = group && group.querySelector(`[data-value="${hit[0]}"]`);
    if (!btn) return;
    group.querySelectorAll('button').forEach((b) => b.classList.remove('video-match'));
    btn.classList.add('video-match');
    const touched = ideaSelection._touched && ideaSelection._touched.category;
    if (!touched) {
      ideaSelection.category = hit[0];
      group.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b === btn)));
      composeIdea();
    }
  }

  function runDeconstruct(videoId) {
    apiPost(`/videos/${videoId}/deconstruct`)
      .then((rec) => {
        state.deconstruction = rec.result_json;
        state.deconstructionFallback = rec.is_fallback;
        state.deconstructPending = false;
        injectCaseIntoCall('deconstruction');
        document.querySelector('#file-meta').textContent = '四维判断已就绪 · 连麦即聊';
      })
      .catch((err) => {
        console.warn('[解构失败]', err.message);
        state.deconstructPending = false;
      });
  }

  // 通话中途把新出炉的案例成果作为系统消息注入,AI 下一轮自然使用,不打断当前话题
  function injectCaseIntoCall(kind) {
    if (!rt.dc || rt.dc.readyState !== 'open') return;
    let text = '';
    if (kind === 'analysis' && state.analysis) {
      text = `【后台通知】用户案例视频的整段解析刚完成。摘要：${state.analysis.summary}` +
        `。请在当前话题告一段落后自然转入案例讨论，不要突兀打断用户。`;
    } else if (kind === 'deconstruction' && state.deconstruction) {
      const d = state.deconstruction;
      const dims = Object.entries(DIM_LABELS)
        .filter(([k]) => d[k])
        .map(([k, label]) => `${label}=${(VERDICT_META[d[k].transfer] || {}).label || d[k].transfer}（${(d[k].transfer_reason || '').slice(0, 40)}）`)
        .join('；');
      text = `【后台通知】案例四维迁移初判已生成：${dims}。${d.overall_note ? `参考价值判断：${d.overall_note}` : ''}` +
        ` 请结合现场所见校准这些初判。`;
    }
    if (!text) return;
    rt.dc.send(JSON.stringify({ type: 'conversation.item.create', item: { type: 'message', role: 'system', content: [{ type: 'input_text', text }] } }));
    logSessionEvent('system', 'case_context_injected', { kind, text });
  }

  // 服务端确定性辅助:每句用户转写发给后端——命中"标签+数字"自动跑保本计算、
  // 命中经营话题自动查平台知识库,返回的后台通知注入对话。
  // 为什么:实测模型不会自主调工具(0/12 场),而注入通道 100% 生效(PRD §23 2026-07-23)。
  async function requestServerAssist(text) {
    if (!rt.sessionId || !text || text.trim().length < 4) return;
    try {
      const res = await apiPost(`/sessions/${rt.sessionId}/skill/advance`, { facts: { latest_user_utterance: text } });
      const msg = res && res.directive && res.directive.message;
      if (msg && rt.dc && rt.dc.readyState === 'open') {
        rt.dc.send(JSON.stringify({ type: 'conversation.item.create', item: { type: 'message', role: 'system', content: [{ type: 'input_text', text: msg }] } }));
      }
    } catch (err) {
      console.warn('[assist]', err && err.message ? err.message : err);
    }
  }

  async function uploadAndAnalyze(file) {
    const max = 200 * 1024 * 1024;
    if (file.size > max) { window.alert('视频超过 200MB，请压缩后再试。'); return; }
    state.video = file; state.demoMode = false;
    await acquireAndAnalyze(
      file.name,
      `${(file.size / 1024 / 1024).toFixed(1)} MB · 正在上传`,
      () => apiUpload(`/stores/${state.storeId}/videos`, file)
    );
  }

  async function ingestUrlAndAnalyze(text) {
    state.demoMode = false;
    await acquireAndAnalyze(
      '链接视频',
      '正在从链接获取视频（受平台限制可能失败）…',
      () => apiPost(`/stores/${state.storeId}/videos/from-url`, { url: text })
    );
  }


  // ── 实时连麦(WebRTC + Qwen Omni Realtime,经雷后端 /realtime/sdp 代理)──
  const rt = {
    pc: null, dc: null, remoteAudio: null, sessionId: null, config: null,
    aiCaption: '', muted: false, bootstrapped: false, cameraFacing: 'environment', reconnecting: false,
  };
  const localVideo = document.querySelector('#local-video');
  const localVideoCanvas = document.querySelector('#local-video-canvas');
  const localVideoCanvasContext = localVideoCanvas.getContext('2d', { alpha: false });
  // 与已通过抖音真机验证的 camtest 环境识别保持一致。
  const useCanvasLocalPreview = /bytedancewebview|ttwebview|aweme|douyin|toutiao/i.test(navigator.userAgent);
  const localPreview = { active: false, animationFrameId: null, videoFrameId: null, lastPaintAt: 0 };

  function stopCanvasLocalPreview() {
    localPreview.active = false;
    if (localPreview.animationFrameId !== null) cancelAnimationFrame(localPreview.animationFrameId);
    if (localPreview.videoFrameId !== null && typeof localVideo.cancelVideoFrameCallback === 'function') {
      localVideo.cancelVideoFrameCallback(localPreview.videoFrameId);
    }
    localPreview.animationFrameId = null;
    localPreview.videoFrameId = null;
    localPreview.lastPaintAt = 0;
    localVideoCanvas.hidden = true;
  }

  function scheduleCanvasLocalPreview() {
    if (!localPreview.active) return;
    if (typeof localVideo.requestVideoFrameCallback === 'function') {
      localPreview.videoFrameId = localVideo.requestVideoFrameCallback(drawCanvasLocalPreview);
      return;
    }
    localPreview.animationFrameId = requestAnimationFrame(drawCanvasLocalPreview);
  }

  function drawCanvasLocalPreview(now) {
    if (!localPreview.active) return;
    localPreview.animationFrameId = null;
    localPreview.videoFrameId = null;
    const throttled = typeof localVideo.requestVideoFrameCallback !== 'function' && now - localPreview.lastPaintAt < 32;
    if (!throttled && localVideo.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && localVideo.videoWidth > 0) {
      if (localVideoCanvas.width !== localVideo.videoWidth || localVideoCanvas.height !== localVideo.videoHeight) {
        localVideoCanvas.width = localVideo.videoWidth;
        localVideoCanvas.height = localVideo.videoHeight;
      }
      try {
        localVideoCanvasContext.drawImage(localVideo, 0, 0, localVideoCanvas.width, localVideoCanvas.height);
        localVideoCanvas.hidden = false;
        localPreview.lastPaintAt = now;
      } catch (err) {
        console.warn('[preview] canvas draw failed, keep native video visible', err);
        stopCanvasLocalPreview();
        return;
      }
    }
    scheduleCanvasLocalPreview();
  }

  async function startLocalPreview(stream) {
    stopCanvasLocalPreview();
    localVideo.srcObject = stream;
    localVideo.hidden = false;
    try { await localVideo.play(); } catch (_) { /* autoplay + playsinline will retry once media is ready */ }
    if (useCanvasLocalPreview) {
      localPreview.active = true;
      scheduleCanvasLocalPreview();
      console.log('[preview] Douyin WebView detected; canvas local preview enabled');
    }
  }

  function stopLocalPreview() {
    stopCanvasLocalPreview();
    localVideo.pause();
    localVideo.srcObject = null;
    localVideo.hidden = true;
  }

  function formatTime(seconds) { return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; }
  function setCallStatus(text, connected) {
    document.querySelector('#call-status-text').textContent = text;
    document.querySelector('.call-status').classList.toggle('connected', !!connected);
  }
  function setAiCaption(text) {
    document.querySelector('#guide-text').textContent = text;
    const cap = document.querySelector('.call-screen .guide-caption');
    if (cap) cap.scrollTop = cap.scrollHeight;
  }
  function startCallTimer() {
    state.elapsed = 0; clearInterval(state.timer);
    state.timer = setInterval(() => { state.elapsed += 1; document.querySelector('#call-time').textContent = formatTime(state.elapsed); }, 1000);
  }

  async function startCall() {
    route('call', true);
    liveConsentModal.hidden = true;
    syncHostNavigation();
    const nextBtn = document.querySelector('#next-guide'); if (nextBtn) nextBtn.style.display = 'none'; // 实时由 AI + 服务端 VAD 驱动,无需手动推进
    setCallStatus('正在连接', false);
    document.querySelector('#ai-state').textContent = 'AI 专家';
    setAiCaption('正在接通…');
    document.querySelector('#video-fallback').hidden = false;
    document.querySelector('#local-video').hidden = true;
    try {
      if (!state.storeId) throw new Error('尚未建档，请先返回填写你想开的店。');
      // 1. 采集音视频(用户现场)
      rt.cameraFacing = 'environment';
      rt.muted = false;
      syncCallControls();
      state.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: rt.cameraFacing } }, audio: true });
      await startLocalPreview(state.stream);
      document.querySelector('#video-fallback').hidden = true;
      // 只有一个摄像头(如笔记本)就不显示"转镜头",不给用户假按钮
      navigator.mediaDevices.enumerateDevices().then((devices) => {
        const cams = devices.filter((d) => d.kind === 'videoinput');
        document.querySelector('#camera-control').hidden = cams.length < 2;
      }).catch(() => {});
      // 2. 建诊断会话 + 取实时配置(指令/工具/VAD/ASR 都在 config.session_update 里)
      const sess = await apiPost(`/stores/${state.storeId}/sessions`);
      rt.sessionId = sess.id; state.sessionId = sess.id;
      rt.config = await fetch(`${API_BASE}/realtime/config/${rt.sessionId}`).then((r) => r.json());
      // 把用户自述与案例解析写入会话事件——它们是会后复盘报告的证据底料
      logSessionEvent('user', 'user_statement', { text: state.profile });
      if (state.analysis) {
        logSessionEvent('system', 'case_analysis', {
          summary: state.analysis.summary,
          claims: (state.analysis.claims || []).map((c) => ({ content: c.content, start_ms: c.start_ms, confidence: c.confidence })),
          video: state.videoMeta ? state.videoMeta.filename : null,
        });
      }
      await connectRealtimeTransport();
      setCallStatus('已连接', true); startSignalMonitor(); startCallTimer();
      setAiCaption('已连接，说说你最想判断什么。');
    } catch (err) {
      showHostMessage('连麦失败：' + (err && err.message ? err.message : err));
      route('upload', true);
      syncHostNavigation();
    }
  }

  async function connectRealtimeTransport() {
    if (!state.stream || !rt.config) throw new Error('实时连麦尚未准备好。');
    // PeerConnection:本地音视频轨(现场)+ 远端 AI 语音 + 事件 data channel
    const pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
    rt.pc = pc;
    rt.bootstrapped = false;
      rt.remoteAudio = document.querySelector('#ai-audio') ||
        Object.assign(document.createElement('audio'), { id: 'ai-audio', autoplay: true });
      if (!rt.remoteAudio.parentNode) document.body.appendChild(rt.remoteAudio);
      pc.ontrack = (e) => { rt.remoteAudio.srcObject = e.streams[0]; };
      state.stream.getTracks().forEach((t) => pc.addTrack(t, state.stream));
      // 事件通道:自建 oai-events 之外,同时接住服务端创建的通道(Qwen 走 ondatachannel)
      const wireChannel = (dc, origin) => {
        rt.dc = dc;
        dc.onopen = () => {
          console.log(`[rt] data channel open (${origin})`);
          // 兜底:部分实现不发 session.created,通道开了就限时等待,超时主动下发指令
          setTimeout(() => sendSessionBootstrap('timeout'), 1500);
        };
        dc.onmessage = (e) => {
          try { handleRealtimeEvent(JSON.parse(e.data)); } catch (_) { console.log('[rt] 非 JSON 事件', e.data); }
        };
      };
      wireChannel(pc.createDataChannel('oai-events'), 'client');
      pc.ondatachannel = (e) => { console.log('[rt] 服务端建通道', e.channel.label); wireChannel(e.channel, 'server'); };
      // 4. Offer → 后端 SDP 代理 → Answer(百炼 Key 不出服务端)
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const answerSdp = await fetch(`${API_ORIGIN}${rt.config.sdp_endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: offer.sdp,
      }).then((r) => { if (!r.ok) throw new Error('SDP 交换失败 HTTP ' + r.status); return r.text(); });
      await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });
  }

  function logSessionEvent(actor, eventType, payload) {
    if (!rt.sessionId) return;
    apiPost(`/sessions/${rt.sessionId}/events`, { actor, event_type: eventType, payload: payload || {} })
      .catch((err) => console.warn('[event 落库失败]', err.message));
  }

  // 下发专家指令/工具/VAD/ASR,并让专家先开口引导;只执行一次
  function sendSessionBootstrap(trigger) {
    if (rt.bootstrapped || !rt.dc || rt.dc.readyState !== 'open') return;
    rt.bootstrapped = true;
    console.log(`[rt] 下发 session.update + response.create (触发:${trigger})`);
    rt.dc.send(JSON.stringify(rt.config.session_update));
    rt.dc.send(JSON.stringify({ type: 'response.create' }));
  }

  function handleRealtimeEvent(evt) {
    if (evt.type !== 'response.audio_transcript.delta') console.log('[rt]', evt.type, evt.error || '');
    switch (evt.type) {
      case 'session.created':
        sendSessionBootstrap('session.created');
        break;
      case 'response.created':
        document.querySelector('#ai-state').textContent = 'AI 专家'; rt.aiCaption = ''; rt.captionLogged = false; break;
      case 'response.audio_transcript.delta':
        rt.aiCaption += (evt.delta || ''); setAiCaption(rt.aiCaption); break;
      case 'response.audio_transcript.done':
        if (evt.transcript) { setAiCaption(evt.transcript); logSessionEvent('assistant', 'transcript', { text: evt.transcript }); rt.captionLogged = true; }
        rt.aiCaption = ''; break;
      case 'response.done':
      case 'response.cancelled':
        // 兜底:用户抢话打断时 audio_transcript.done 不会来,已累积的半句话在此补落库,避免对话记录缺失
        if (!rt.captionLogged && rt.aiCaption.trim()) {
          logSessionEvent('assistant', 'transcript', { text: rt.aiCaption.trim(), interrupted: true });
          rt.captionLogged = true;
        }
        rt.aiCaption = '';
        break;
      case 'conversation.item.input_audio_transcription.completed':
        if (evt.transcript) {
          logSessionEvent('user', 'transcript', { text: evt.transcript });
          requestServerAssist(evt.transcript); // 不 await:辅助注入失败不影响通话
        }
        break;
      case 'response.function_call_arguments.done':
        handleToolCall(evt); break;
      case 'error':
        console.error('[realtime error]', evt.error || evt);
        // 报错落库,回看页可见,作为改进参照
        logSessionEvent('system', 'realtime_error', { error: evt.error || evt });
        break;
      default: break;
    }
  }

  async function handleToolCall(evt) {
    const toolState = document.querySelector('#tool-state');
    document.querySelector('#ai-state').textContent = 'AI 正在检索';
    if (toolState) { toolState.hidden = false; toolState.querySelector('span').textContent = `正在调用 ${evt.name || '工具'}…`; }
    let output;
    try {
      const args = evt.arguments ? JSON.parse(evt.arguments) : {};
      const res = await apiPost(`/sessions/${rt.sessionId}/tools/execute`, { call_id: evt.call_id, tool_name: evt.name, arguments: args });
      output = res.result || res;
    } catch (err) {
      output = { status: 'unavailable', error: String(err && err.message ? err.message : err) };
    }
    if (rt.dc && rt.dc.readyState === 'open') {
      rt.dc.send(JSON.stringify({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: evt.call_id, output: JSON.stringify(output) } }));
      rt.dc.send(JSON.stringify({ type: 'response.create' }));
    }
    if (toolState) toolState.hidden = true;
    document.querySelector('#ai-state').textContent = 'AI 专家';
  }

  function showNetworkToast(message) {
    const toast = document.querySelector('#network-toast');
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(showNetworkToast.timer);
    showNetworkToast.timer = setTimeout(() => { toast.hidden = true; }, 1800);
  }

  function syncCallControls() {
    const muteButton = document.querySelector('#mute-control');
    const cameraButton = document.querySelector('#camera-control');
    muteButton.setAttribute('aria-pressed', String(rt.muted));
    muteButton.classList.toggle('is-muted', rt.muted);
    muteButton.setAttribute('aria-label', rt.muted ? '开麦（让口袋哥听到你）' : '闭麦（口袋哥听不到你）');
    muteButton.title = rt.muted ? '开麦' : '闭麦';
    muteButton.querySelector('small').textContent = rt.muted ? '开麦' : '闭麦';
    const switchingTo = rt.cameraFacing === 'environment' ? '前置' : '后置';
    cameraButton.setAttribute('aria-label', `切换到${switchingTo}镜头`);
    cameraButton.title = `切换到${switchingTo}镜头`;
    cameraButton.querySelector('small').textContent = '转镜头';
  }

  // 信号条 = 真实网络质量(WebRTC RTT):<0.15s 满格,<0.3s 三格,<0.5s 两格,更差一格
  function startSignalMonitor() {
    stopSignalMonitor();
    const el = document.querySelector('.signal-indicator');
    if (!el) return;
    rt.signalTimer = setInterval(async () => {
      if (!rt.pc) return;
      const cs = rt.pc.connectionState;
      if ((cs === 'failed' || cs === 'disconnected') && (rt.reconnectTries || 0) < 2) { attemptAutoReconnect(); return; }
      try {
        const stats = await rt.pc.getStats();
        let rtt = null;
        stats.forEach((report) => {
          if (report.type === 'candidate-pair' && report.state === 'succeeded' && report.currentRoundTripTime != null) {
            rtt = report.currentRoundTripTime;
          }
        });
        const level = rtt == null ? 1 : rtt < 0.15 ? 4 : rtt < 0.3 ? 3 : rtt < 0.5 ? 2 : 1;
        el.dataset.level = String(level);
        el.setAttribute('aria-label', `网络信号${level >= 4 ? '很好' : level === 3 ? '良好' : level === 2 ? '一般' : '较差'}`);
      } catch (_) { /* 统计失败保持现状 */ }
    }, 3000);
  }
  function stopSignalMonitor() {
    clearInterval(rt.signalTimer);
    const el = document.querySelector('.signal-indicator');
    if (el) delete el.dataset.level;
  }

  function closeRealtimeTransport() {
    if (rt.dc) { try { rt.dc.close(); } catch (_) {} }
    if (rt.pc) { try { rt.pc.close(); } catch (_) {} }
    rt.pc = null;
    rt.dc = null;
    rt.bootstrapped = false;
    stopSignalMonitor();
  }

  document.querySelector('#mute-control').addEventListener('click', () => {
    if (!state.stream) return;
    rt.muted = !rt.muted;
    state.stream.getAudioTracks().forEach((track) => { track.enabled = !rt.muted; });
    syncCallControls();
    showNetworkToast(rt.muted ? '已闭麦，口袋哥听不到你' : '已开麦');
  });

  document.querySelector('#camera-control').addEventListener('click', async (event) => {
    if (!state.stream) return;
    const button = event.currentTarget;
    const targetFacing = rt.cameraFacing === 'environment' ? 'user' : 'environment';
    button.disabled = true;
    try {
      const replacement = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: targetFacing } }, audio: false,
      });
      const nextTrack = replacement.getVideoTracks()[0];
      if (!nextTrack) throw new Error('未找到可用镜头');
      const sender = rt.pc && rt.pc.getSenders().find((item) => item.track && item.track.kind === 'video');
      if (sender) await sender.replaceTrack(nextTrack);
      const previousTrack = state.stream.getVideoTracks()[0];
      if (previousTrack) { state.stream.removeTrack(previousTrack); previousTrack.stop(); }
      state.stream.addTrack(nextTrack);
      rt.cameraFacing = targetFacing;
      await startLocalPreview(state.stream);
      syncCallControls();
      showNetworkToast(`已切换到${targetFacing === 'user' ? '前置' : '后置'}镜头`);
    } catch (err) {
      showNetworkToast('切换镜头失败，请检查权限');
      console.warn('[camera] switch failed', err);
    } finally {
      button.disabled = false;
    }
  });

  // 断线自动重连(用户无需操心连接管理;连续失败 2 次后如实提示)
  async function attemptAutoReconnect() {
    if (rt.reconnecting || !state.stream || !rt.sessionId || !rt.config) return;
    rt.reconnecting = true;
    rt.reconnectTries = (rt.reconnectTries || 0) + 1;
    setCallStatus('正在重连', false);
    showNetworkToast('网络波动，正在自动重连…');
    try {
      closeRealtimeTransport();
      await connectRealtimeTransport();
      setCallStatus('已连接', true); startSignalMonitor();
      rt.reconnectTries = 0;
      setAiCaption('已重新连接，请继续展示现场。');
      showNetworkToast('已重新连接');
    } catch (err) {
      setCallStatus('连接中断', false);
      showNetworkToast(rt.reconnectTries < 2 ? '重连失败，稍后自动再试' : '网络持续异常，请结束后重新发起连麦');
      console.warn('[realtime] reconnect failed', err);
    } finally {
      rt.reconnecting = false;
    }
  }
  document.querySelector('#end-call').addEventListener('click', endCall);
  // ── 咨询历史(存在浏览器 localStorage,跨会话可见)──
  const HISTORY_KEY = 'pm_history';
  const loadHistory = () => { try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; } catch (_) { return []; } };
  function saveHistoryEntry(sessionId) {
    const items = loadHistory().filter((it) => it.id !== sessionId);
    items.unshift({ id: sessionId, title: state.profile.slice(0, 40), ts: Date.now() });
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 10))); } catch (_) { /* 隐私模式等存不了就算了 */ }
  }
  function renderHistory() {
    const wrap = document.querySelector('#history-list');
    if (!wrap) return;
    const items = loadHistory();
    wrap.hidden = items.length === 0;
    document.querySelector('#history-items').innerHTML = items.map((it) => {
      const d = new Date(it.ts);
      const when = `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
      return `<button type="button" class="history-item" data-session="${it.id}"><span>${escHtml(it.title)}</span><small>${when} · 看复盘 ›</small></button>`;
    }).join('');
  }
  document.addEventListener('click', async (event) => {
    const item = event.target.closest('.history-item');
    if (!item) return;
    try {
      const rec = await fetch(`${API_BASE}/sessions/${item.dataset.session}/report`).then((r) => { if (!r.ok) throw new Error('报告不存在或已清理'); return r.json(); });
      state.deconstruction = null; // 历史复盘只有报告本体,不带解构上下文
      renderRecap(rec);
      route('recap');
    } catch (err) {
      showHostMessage('打开历史复盘失败：' + err.message);
    }
  });

  async function endCall() {
    clearInterval(state.timer);
    closeRealtimeTransport();
    stopLocalPreview();
    if (state.stream) state.stream.getTracks().forEach((t) => t.stop());
    state.stream = null;
    route('recap-loading', true);
    try {
      if (!rt.sessionId) throw new Error('无会话');
      document.querySelector('#recap-loading-text').textContent = 'AI 专家正在综合案例与本次对话，生成你的建议…';
      await apiPost(`/sessions/${rt.sessionId}/complete`);
      const rec = await fetch(`${API_BASE}/sessions/${rt.sessionId}/report`).then((r) => { if (!r.ok) throw new Error('报告获取失败 ' + r.status); return r.json(); });
      renderRecap(rec);
      saveHistoryEntry(rt.sessionId);
      route('recap', true);
    } catch (err) {
      document.querySelector('#recap-loading-text').textContent = '复盘生成失败:' + (err && err.message ? err.message : err);
    }
  }

  // 把后端 DiagnosisReport 渲染进复盘屏(真实建议,替换写死文案)
  // 口袋哥收尾金句:一句话、有态度、可分享(把握度低时自动带"先别急"语气)
  const CONCLUSION_HEADLINE = {
    proceed: '这个案例的路子你可以学，按下面的步骤动起来。',
    conditional_proceed: '能做，但先把下面几件事验证清楚再动钱。',
    do_not_proceed: '这个案例别照搬，钱包要紧，先看下面的原因。',
    rectify: '这事能做，但先把几处硬伤改掉再动钱。',
    observe: '别急着签，先观察验证这几件事。',
    stop_loss: '这个方向先停一停，钱包要紧。',
    insufficient_data: '先小成本验证，暂时别急着签铺。',
  };
  const DIM_LABELS = { location: '选址', product: '产品', audience: '客群', operation: '运营' };
  const VERDICT_META = {
    learnable: { label: '可以学', cls: 'yes' },
    adapt_required: { label: '需要改', cls: 'adapt' },
    not_replicable: { label: '不可照搬', cls: 'no' },
    to_verify: { label: '待验证', cls: 'adapt' },
  };
  const firstSentence = (t) => {
    const s = String(t || '').split(/(?<=[。！？!?])/)[0] || '';
    return s.trim();
  };
  function renderRecap(rec) {
    const rpt = rec.report || {};
    const d = state.deconstruction;
    // 口袋哥气泡 = 一句金句,不再塞整段报告
    const title = document.querySelector('#recap-title');
    if (title) title.textContent = CONCLUSION_HEADLINE[rpt.conclusion] || firstSentence(rpt.summary) || 'AI 专家已生成本次建议。';
    const blocks = document.querySelectorAll('.recap-sections .recap-block');
    if (blocks.length < 3) return;
    // 01 · 别人为什么成功(来自四维解构,每维一句)
    if (d) {
      blocks[0].querySelector('div').innerHTML =
        `<h2>这家店为什么能火</h2><ul>${Object.entries(DIM_LABELS)
          .filter(([k]) => d[k])
          .map(([k, label]) => `<li><b>${label}</b>｜${escHtml(firstSentence(d[k].why_it_works))}</li>`).join('')}</ul>`;
    } else {
      blocks[0].querySelector('div').innerHTML =
        `<h2>本次咨询回顾</h2><ul>${(rpt.summary ? rpt.summary.split(/(?<=[。！？])/).filter(Boolean).slice(0, 3) : ['本次未上传案例视频。'])
          .map((s) => `<li>${escHtml(s.trim())}</li>`).join('')}</ul>`;
    }
    // 02 · 你能学什么/不能照搬什么(四档判断行,直接可扫读)
    const gaps = (rpt.information_gaps || []);
    if (d) {
      blocks[1].querySelector('div').innerHTML = Object.entries(DIM_LABELS)
        .filter(([k]) => d[k])
        .map(([k, label]) => {
          const v = VERDICT_META[d[k].transfer] || VERDICT_META.to_verify;
          return `<div class="verdict-row ${v.cls}"><span class="verdict-chip">${v.label}</span>` +
            `<div class="verdict-body"><b class="verdict-dim">${label}</b><p>${escHtml(firstSentence(d[k].transfer_reason))}</p></div></div>`;
        }).join('') +
        (rec.is_fallback ? '<div class="verdict-row no"><span class="verdict-chip">降级</span><div class="verdict-body"><b class="verdict-dim">降级说明</b><p>本报告为降级版本，结论仅供参考。</p></div></div>' : '');
    } else {
      const cls = ['stop_loss', 'do_not_proceed'].includes(rpt.conclusion) ? 'no' : ['rectify', 'conditional_proceed', 'observe', 'insufficient_data'].includes(rpt.conclusion) ? 'adapt' : 'yes';
      const chip = cls === 'no' ? '先停' : cls === 'adapt' ? '先验证' : '可以做';
      blocks[1].querySelector('div').innerHTML =
        `<div class="verdict-row ${cls}"><span class="verdict-chip">${chip}</span>` +
        `<div class="verdict-body"><b class="verdict-dim">总体结论</b><p>${escHtml(CONCLUSION_HEADLINE[rpt.conclusion] || String(rpt.conclusion || ''))}</p></div></div>`;
    }
    // 03 · 下一步(时限 + 一件事,达成标准收进小字)
    const acts = [...(rpt.immediate_actions || []), ...(rpt.short_term_actions || [])];
    blocks[2].querySelector('div').innerHTML =
      `<h2>先完成这 ${acts.length || 1} 件事</h2><ol>${acts.length
        ? acts.map((a) => `<li><b>${escHtml(a.timeframe || '')}</b><span>${escHtml(a.title)}${a.success_metric ? `<small>做到什么算完成：${escHtml(a.success_metric)}</small>` : ''}</span></li>`).join('')
        : '<li><span>先补齐待验证信息，再进行下一次连麦。</span></li>'}</ol>`;
    // 底部:完整专业诊断折叠收纳(summary/问题清单/待验证/把握度)
    const sections = document.querySelector('.recap-sections');
    let detail = sections.querySelector('.recap-detail');
    if (!detail) {
      detail = document.createElement('details');
      detail.className = 'recap-detail';
      sections.appendChild(detail);
    }
    const probs = (rpt.problems || []);
    detail.innerHTML =
      `<summary>查看完整专家诊断（把握度 ${Math.round((rpt.confidence || 0) * 100)}%）</summary>` +
      `<p>${escHtml(rpt.summary || '')}</p>` +
      (probs.length ? `<ul>${probs.map((p) => `<li><b>[${escHtml(p.priority || '')}]</b> ${escHtml(p.title)}</li>`).join('')}</ul>` : '') +
      (gaps.length ? `<p><b>还需要验证：</b>${gaps.map(escHtml).join('；')}</p>` : '');
  }

  route('welcome', true); updateProfileSummary();
  // dev 调试钩子(不影响产品逻辑):无摄像头环境下验证渲染用
  window.__pm = { route, renderRecap, state, rt };
})();


