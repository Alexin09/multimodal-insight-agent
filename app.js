// ============================================================
// app.js — SPA Router, Sessions, Market, Settings, Chat flow
// ============================================================

// ==================== DATA ====================

const MCP_TOOLS = [
  { avatar:'🔍', title:'find_tables', desc:'在指定 schema 下搜索数据库表，支持模糊名称过滤，快速定位目标数据表。', tags:['MCP','Schema','Discovery'], bg:'#1a2a4e' },
  { avatar:'📋', title:'get_table_schema', desc:'获取表的完整列定义（列名、类型、注释），支持普通表和物化视图。', tags:['MCP','Schema','Metadata'], bg:'#1a3a2e' },
  { avatar:'⚡', title:'run_public_sql_query', desc:'执行只读 SQL 查询，自动限制行数、超时保护，拒绝危险写操作。', tags:['MCP','SQL','Query'], bg:'#2a1a4e' },
];

const MODALITIES = [
  { avatar:'💬', title:'自然语言查询', desc:'用中文或英文提问，自动转换为 SQL 并查询数据库，返回结构化结果与分析。', tags:['Text','NL2SQL'], bg:'#1a2a3a' },
  { avatar:'🖼️', title:'图像识别', desc:'上传截图或数据图表，通过 GLM-OCR 提取文字后路由到 SQL 查询或 GPT-4o Vision 分析。', tags:['Vision','OCR'], bg:'#2a2a1a' },
  { avatar:'🎤', title:'语音输入', desc:'按住麦克风录音，Whisper 自动转文字后进入分析流程，解放双手。', tags:['ASR','Whisper'], bg:'#2a1a1a' },
  { avatar:'🔊', title:'语音播报', desc:'分析结果自动生成语音摘要，通过 Edge-TTS 高质量合成播放。', tags:['TTS','Audio'], bg:'#1a1a3a' },
  { avatar:'📊', title:'自动图表', desc:'查询结果自动判断数据形态，生成折线图、柱状图等可视化，嵌入回复中。', tags:['Chart','Matplotlib'], bg:'#3a2a1a' },
];

const WORKFLOWS = [
  { avatar:'🧠', title:'意图分类', desc:'LLM 驱动的意图识别：文本查询 / 图像分析 / 混合模态 / 通用对话，精准路由。', tags:['Router','LLM'], bg:'#2a1a3a' },
  { avatar:'🗄️', title:'Schema 发现', desc:'关键词匹配 + MCP 工具动态获取表结构，为 Agent 提供精确的数据上下文。', tags:['Schema','Context'], bg:'#1a3a4e' },
  { avatar:'🤖', title:'ReAct Agent', desc:'最多 12 轮工具调用循环，支持 SQL 错误自修复（最多 2 次重试），直到获得最终答案。', tags:['Agent','Loop'], bg:'#3a1a2a' },
  { avatar:'📡', title:'SSE 流式输出', desc:'实时事件流推送：进度状态（3 步指示器）→ 逐词流式回答，零等待体验。', tags:['SSE','Streaming'], bg:'#1a2a2a' },
];

const SESSIONS_DEFAULT = [
  { id:'inbox', avatar:'🤯', title:'数据洞察', desc:'多模态智能数据分析', pinned:true },
];

const SETTINGS_TABS = {
  connection: `
    <div class="settings-section">
      <div class="settings-section-title">后端服务</div>
      <div class="settings-row"><div class="settings-row-label">API 地址<small>polydata-insight 后端地址</small></div><input class="settings-input" id="settingApiBase" value="${localStorage.getItem('mia_api_base') || 'http://localhost:8000'}" placeholder="http://localhost:8000"></div>
      <div class="settings-row"><div class="settings-row-label">连接状态<small>检测后端是否可达</small></div><span id="connStatus"><span class="status-dot offline"></span>未检测</span><button class="btn btn-default" style="min-width:80px;height:32px;margin-left:12px" onclick="checkConnection()">检测</button></div>
      <div class="settings-row"><div class="settings-row-label">数据库模式<small>后端当前使用的数据源</small></div><span id="dbModeDisplay">-</span></div>
    </div>
    <div class="settings-section">
      <div class="settings-section-title">操作</div>
      <div class="settings-row"><div class="settings-row-label">保存设置<small>保存 API 地址到本地存储</small></div><button class="btn btn-primary" style="min-width:80px;height:32px" onclick="saveSettings()">保存</button></div>
    </div>`,
  model: `
    <div class="settings-section">
      <div class="settings-section-title">模型配置</div>
      <div class="settings-row"><div class="settings-row-label">LLM 模型<small>后端使用的语言模型</small></div><select class="settings-select"><option>gpt-4o</option><option>gpt-4-turbo</option><option>gpt-3.5-turbo</option></select></div>
      <div class="settings-row"><div class="settings-row-label">Temperature<small>值越大回复越随机（0.0 推荐）</small></div><input class="settings-input" type="number" value="0.0" step="0.1" min="0" max="2" style="min-width:100px"></div>
      <div class="settings-row"><div class="settings-row-label">最大行数<small>SQL 查询结果最大返回行数</small></div><input class="settings-input" type="number" value="500" style="min-width:100px"></div>
      <div class="settings-row"><div class="settings-row-label">查询超时<small>SQL 执行超时（秒）</small></div><input class="settings-input" type="number" value="60" style="min-width:100px"></div>
    </div>`,
  voice: `
    <div class="settings-section">
      <div class="settings-section-title">语音合成 (TTS)</div>
      <div class="settings-row"><div class="settings-row-label">TTS 引擎<small>文字转语音服务</small></div><select class="settings-select"><option>Edge TTS</option><option>OpenAI TTS</option></select></div>
      <div class="settings-row"><div class="settings-row-label">默认语音<small>合成语音角色</small></div><select class="settings-select"><option>zh-CN-XiaoxiaoNeural</option><option>zh-CN-YunxiNeural</option><option>en-US-AriaNeural</option></select></div>
      <div class="settings-row"><div class="settings-row-label">自动播放<small>回复完成后自动播放语音摘要</small></div><button class="settings-toggle on" onclick="this.classList.toggle('on')"></button></div>
    </div>
    <div class="settings-section">
      <div class="settings-section-title">语音识别 (ASR)</div>
      <div class="settings-row"><div class="settings-row-label">ASR 引擎<small>语音转文字服务</small></div><select class="settings-select"><option>OpenAI Whisper</option><option>浏览器原生</option></select></div>
    </div>`,
  about: `
    <div class="about-card">
      <div class="about-logo"><img src="logo.png" alt="MIA"></div>
      <div class="about-name">MultiModal Insight Agent</div>
      <div class="about-version">v1.0.0 &middot; Based on LobeChat UI</div>
      <p style="color:var(--text2);font-size:14px;max-width:500px;line-height:1.6">多模态数据洞察助手 — 文本、语音、图像输入<br>MCP 工具链驱动的 Text-to-SQL 智能分析<br>SSE 流式响应 + 实时进度追踪</p>
      <div class="about-links">
        <a href="https://github.com/lobehub/lobe-chat" target="_blank">LobeChat</a>
        <a href="#" onclick="navigate('market');return false">能力一览</a>
      </div>
    </div>`
};

// ==================== STATE ====================

let currentPage = 'welcome';
let sessions = [...SESSIONS_DEFAULT];
let currentSession = 'inbox';
let conversations = {};      // sessionId -> { messages[], history[] }
let isStreaming = false;
let abortController = null;

// Image attachments for current input
let attachedImages = [];

// Voice recording
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let isTranscribing = false;

// ==================== NAVIGATION ====================

function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const target = document.getElementById('page-' + page);
  if (target) { target.classList.add('active'); currentPage = page; }
  document.querySelectorAll('.sidebar-icon[data-page]').forEach(el => {
    el.classList.toggle('active', el.dataset.page === page || (el.dataset.page === 'welcome' && page === 'chat'));
  });
}

document.querySelectorAll('.sidebar-icon[data-page]').forEach(el => {
  el.addEventListener('click', () => {
    const page = el.dataset.page;
    if (page === 'welcome' && currentPage === 'welcome') navigate('chat');
    else if (page === 'welcome' && currentPage === 'chat') navigate('welcome');
    else navigate(page);
  });
});

// ==================== SESSIONS ====================

function renderSessions() {
  const list = document.getElementById('sessionList');
  const pinned = sessions.filter(s => s.pinned);
  const others = sessions.filter(s => !s.pinned);
  let html = '';
  if (pinned.length) {
    html += '<div class="session-group-label">置顶</div>';
    pinned.forEach(s => html += sessionHTML(s));
  }
  if (others.length) {
    html += '<div class="session-group-label">对话列表</div>';
    others.forEach(s => html += sessionHTML(s));
  }
  list.innerHTML = html;
  list.querySelectorAll('.session-item').forEach(el => {
    el.addEventListener('click', () => selectSession(el.dataset.id));
  });
}

function sessionHTML(s) {
  return `<div class="session-item ${s.id === currentSession ? 'active' : ''}" data-id="${s.id}">
    <div class="session-item-avatar">${s.avatar}</div>
    <div class="session-item-info">
      <div class="session-item-title">${escHTML(s.title)}</div>
      <div class="session-item-desc">${escHTML(s.desc)}</div>
    </div>
  </div>`;
}

function selectSession(id) {
  currentSession = id;
  const s = sessions.find(s => s.id === id);
  if (s) {
    document.getElementById('chatAvatar').textContent = s.avatar;
    document.getElementById('chatTitle').textContent = s.title;
    document.getElementById('chatDesc').textContent = s.desc;
  }
  renderSessions();
  renderChatMessages();
}

function createNewSession() {
  const id = 's' + Date.now();
  sessions.push({ id, avatar:'🔎', title:'新的查询', desc:'开始新的数据分析...', pinned:false });
  selectSession(id);
}

function toggleSessionPanel() {
  document.getElementById('sessionPanel').classList.toggle('collapsed');
}

document.getElementById('sessionSearch')?.addEventListener('input', (e) => {
  const q = e.target.value.toLowerCase();
  document.querySelectorAll('.session-item').forEach(el => {
    const title = el.querySelector('.session-item-title')?.textContent.toLowerCase() || '';
    el.style.display = (!q || title.includes(q)) ? '' : 'none';
  });
});

// ==================== CHAT RENDERING ====================

function getConv() {
  if (!conversations[currentSession]) conversations[currentSession] = { messages: [], history: [] };
  return conversations[currentSession];
}

function renderChatMessages() {
  const container = document.getElementById('chatMessages');
  const conv = getConv();
  const welcome = document.getElementById('chatWelcome');

  // Remove old message rows
  container.querySelectorAll('.msg-row').forEach(el => el.remove());

  if (conv.messages.length === 0) {
    welcome.style.display = 'flex';
  } else {
    welcome.style.display = 'none';
    conv.messages.forEach(m => {
      container.insertAdjacentHTML('beforeend', renderMessageHTML(m));
    });
  }
  container.scrollTop = container.scrollHeight;
}

function renderMessageHTML(m) {
  if (m.role === 'user') {
    let imgsHtml = '';
    if (m.images && m.images.length) {
      imgsHtml = '<div class="user-images">' + m.images.map(src => `<img src="${src}" alt="Uploaded">`).join('') + '</div>';
    }
    return `<div class="msg-row user">
      <div class="msg-avatar user-av"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg></div>
      <div class="msg-bubble">${imgsHtml}${m.content ? '<p>' + escHTML(m.content) + '</p>' : ''}</div>
    </div>`;
  }

  // Assistant
  const toolHtml = renderToolStatus(m.toolCalls || [], !m.done);
  const contentHtml = m.content ? `<div class="msg-markdown">${renderMarkdown(m.content)}</div>` : '';
  const errorHtml = m.error ? `<div class="msg-error"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>${escHTML(m.error)}</div>` : '';
  const actionsHtml = m.done && m.content ? `<div class="msg-actions">
    <button class="msg-action-btn" title="复制" onclick="copyMsg(this,'${m.id}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
    <button class="msg-action-btn" title="朗读" onclick="playTTS('${m.id}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg></button>
  </div>` : '';

  return `<div class="msg-row assistant" id="msg-${m.id}">
    <div class="msg-avatar assistant-av"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg></div>
    <div class="msg-bubble">${toolHtml}${contentHtml}${errorHtml}${actionsHtml}</div>
  </div>`;
}

// Live-update a single assistant message DOM (avoid full re-render during streaming)
function updateAssistantMsg(m) {
  const el = document.getElementById('msg-' + m.id);
  if (!el) {
    // Not yet in DOM, append it
    document.getElementById('chatMessages').insertAdjacentHTML('beforeend', renderMessageHTML(m));
  } else {
    const bubble = el.querySelector('.msg-bubble');
    if (bubble) {
      const toolHtml = renderToolStatus(m.toolCalls || [], !m.done);
      const contentHtml = m.content ? `<div class="msg-markdown">${renderMarkdown(m.content)}</div>` : '';
      const errorHtml = m.error ? `<div class="msg-error">${escHTML(m.error)}</div>` : '';
      const actionsHtml = m.done && m.content ? `<div class="msg-actions">
        <button class="msg-action-btn" title="复制" onclick="copyMsg(this,'${m.id}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
        <button class="msg-action-btn" title="朗读" onclick="playTTS('${m.id}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg></button>
      </div>` : '';
      bubble.innerHTML = toolHtml + contentHtml + errorHtml + actionsHtml;
    }
  }
  const container = document.getElementById('chatMessages');
  container.scrollTop = container.scrollHeight;
}

// ==================== CHAT FLOW ====================

async function handleSend() {
  const textarea = document.getElementById('chatInput');
  const text = textarea.value.trim();
  if ((!text && !attachedImages.length) || isStreaming) return;

  const conv = getConv();

  // Add user message
  const userMsg = {
    id: 'u' + Date.now(),
    role: 'user',
    content: text,
    images: attachedImages.length ? [...attachedImages] : undefined,
    done: true
  };
  conv.messages.push(userMsg);

  // Update session desc
  const s = sessions.find(s => s.id === currentSession);
  if (s && text) { s.desc = text.slice(0, 30) + (text.length > 30 ? '...' : ''); renderSessions(); }

  // Clear input
  textarea.value = '';
  textarea.style.height = 'auto';
  attachedImages = [];
  renderImagePreviews();

  // Hide welcome
  document.getElementById('chatWelcome').style.display = 'none';
  // Append user message to DOM
  document.getElementById('chatMessages').insertAdjacentHTML('beforeend', renderMessageHTML(userMsg));

  // Create assistant message placeholder
  const assistantMsg = {
    id: 'a' + Date.now(),
    role: 'assistant',
    content: '',
    toolCalls: [],
    done: false
  };
  conv.messages.push(assistantMsg);
  updateAssistantMsg(assistantMsg);

  // Build history for API (OpenAI format)
  const history = conv.history.slice(-10); // Last 10 turns

  // Start streaming
  isStreaming = true;
  updateSendButton();
  abortController = new AbortController();

  try {
    for await (const delta of streamChat(text, history, userMsg.images || [], abortController.signal)) {
      switch (delta.type) {
        case 'tool_call': {
          const existing = assistantMsg.toolCalls.findIndex(tc => tc.name === delta.toolCall.name);
          if (existing >= 0) assistantMsg.toolCalls[existing] = delta.toolCall;
          else assistantMsg.toolCalls.push(delta.toolCall);
          updateAssistantMsg(assistantMsg);
          break;
        }
        case 'content':
          assistantMsg.content += delta.content;
          updateAssistantMsg(assistantMsg);
          break;
        case 'error':
          assistantMsg.error = delta.error;
          assistantMsg.done = true;
          updateAssistantMsg(assistantMsg);
          break;
        case 'done':
          assistantMsg.done = true;
          updateAssistantMsg(assistantMsg);
          break;
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      assistantMsg.error = err.message || '请求失败';
      assistantMsg.done = true;
      updateAssistantMsg(assistantMsg);
    }
  }

  assistantMsg.done = true;
  updateAssistantMsg(assistantMsg);

  // Update history
  conv.history.push({ role: 'user', content: text });
  if (assistantMsg.content) conv.history.push({ role: 'assistant', content: assistantMsg.content });

  isStreaming = false;
  abortController = null;
  updateSendButton();

  // Auto-play TTS if VOICE_SUMMARY detected
  if (assistantMsg.content?.includes('<!-- VOICE_SUMMARY -->')) {
    setTimeout(() => playTTS(assistantMsg.id), 300);
  }
}

function stopStreaming() {
  if (abortController) abortController.abort();
  isStreaming = false;
  updateSendButton();
}

function updateSendButton() {
  const btn = document.getElementById('sendBtn');
  if (isStreaming) {
    btn.classList.add('stop-mode');
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';
    btn.onclick = stopStreaming;
  } else {
    btn.classList.remove('stop-mode');
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
    btn.onclick = handleSend;
  }
}

function quickAsk(el) {
  document.getElementById('chatInput').value = el.textContent;
  navigate('chat');
  setTimeout(handleSend, 100);
}

// Enter to send
document.getElementById('chatInput')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
});

// Auto-resize textarea
document.getElementById('chatInput')?.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 200) + 'px';
});

// ==================== IMAGE UPLOAD ====================

function renderImagePreviews() {
  const container = document.getElementById('imagePreviews');
  container.innerHTML = attachedImages.map((src, i) =>
    `<div class="preview-item"><img src="${src}" alt="Preview"><button class="preview-remove" onclick="removeImage(${i})">×</button></div>`
  ).join('');
}

function removeImage(i) {
  attachedImages.splice(i, 1);
  renderImagePreviews();
}

document.getElementById('fileInput')?.addEventListener('change', (e) => {
  for (const file of e.target.files) {
    if (!file.type.startsWith('image/')) continue;
    const reader = new FileReader();
    reader.onload = () => { attachedImages.push(reader.result); renderImagePreviews(); };
    reader.readAsDataURL(file);
  }
  e.target.value = '';
});

// Paste image
document.getElementById('chatInput')?.addEventListener('paste', (e) => {
  for (const item of (e.clipboardData?.items || [])) {
    if (!item.type.startsWith('image/')) continue;
    e.preventDefault();
    const file = item.getAsFile();
    if (!file) continue;
    const reader = new FileReader();
    reader.onload = () => { attachedImages.push(reader.result); renderImagePreviews(); };
    reader.readAsDataURL(file);
  }
});

// ==================== VOICE RECORDING ====================

document.getElementById('micBtn')?.addEventListener('click', async () => {
  if (isRecording) {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
    isRecording = false;
    document.getElementById('micBtn').classList.remove('recording');
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(audioChunks, { type: 'audio/webm' });
      isTranscribing = true;
      document.getElementById('micBtn').classList.add('transcribing');
      try {
        const text = await transcribeAudio(blob);
        if (text) {
          const ta = document.getElementById('chatInput');
          ta.value += (ta.value ? ' ' : '') + text;
          ta.dispatchEvent(new Event('input'));
        }
      } catch (err) { console.error('ASR error:', err); }
      isTranscribing = false;
      document.getElementById('micBtn').classList.remove('transcribing');
    };
    mediaRecorder.start();
    isRecording = true;
    document.getElementById('micBtn').classList.add('recording');
  } catch (err) { console.error('Mic denied:', err); }
});

// ==================== MESSAGE ACTIONS ====================

function copyMsg(btn, msgId) {
  const conv = getConv();
  const msg = conv.messages.find(m => m.id === msgId);
  if (!msg?.content) return;
  navigator.clipboard.writeText(msg.content).then(() => {
    btn.classList.add('active');
    setTimeout(() => btn.classList.remove('active'), 2000);
  });
}

let currentAudio = null;
function playTTS(msgId) {
  const conv = getConv();
  const msg = conv.messages.find(m => m.id === msgId);
  if (!msg?.content) return;

  if (currentAudio) { currentAudio.pause(); currentAudio = null; }

  const voiceText = getVoiceText(msg.content);
  if (!voiceText) return;

  synthesizeSpeech(voiceText).then(blob => {
    const url = URL.createObjectURL(blob);
    currentAudio = new Audio(url);
    currentAudio.play();
    currentAudio.onended = () => { currentAudio = null; URL.revokeObjectURL(url); };
  }).catch(err => console.error('TTS error:', err));
}

// ==================== MARKET ====================

function renderMarket() {
  renderCardGrid('mcpToolsGrid', MCP_TOOLS);
  renderCardGrid('modalityGrid', MODALITIES);
  renderCardGrid('workflowGrid', WORKFLOWS);
}

function renderCardGrid(gridId, items) {
  document.getElementById(gridId).innerHTML = items.map(a =>
    `<div class="agent-card">
      <div class="agent-card-banner" style="background:${a.bg || 'var(--bg2)'}"><div class="agent-card-banner-blur">${a.avatar}</div></div>
      <div class="agent-card-body">
        <div class="agent-card-top">
          <div class="agent-card-title">${escHTML(a.title)}</div>
          <div class="agent-card-avatar">${a.avatar}</div>
        </div>
        <div class="agent-card-desc">${escHTML(a.desc)}</div>
        <div class="agent-card-tags">${a.tags.map(t => `<span>${t}</span>`).join('')}</div>
      </div>
    </div>`
  ).join('');
}

// ==================== SETTINGS ====================

function renderSettingsTab(tab) {
  document.getElementById('settingsContent').innerHTML = SETTINGS_TABS[tab] || '';
  document.querySelectorAll('.settings-menu-item').forEach(el => {
    el.classList.toggle('active', el.dataset.tab === tab);
  });
}

document.querySelectorAll('.settings-menu-item').forEach(el => {
  el.addEventListener('click', () => renderSettingsTab(el.dataset.tab));
});

async function checkConnection() {
  const base = document.getElementById('settingApiBase')?.value || API_BASE;
  const status = document.getElementById('connStatus');
  try {
    const res = await fetch(base + '/health', { signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      status.innerHTML = '<span class="status-dot online"></span>已连接';
      // Try to get models info
      try {
        const models = await (await fetch(base + '/v1/models')).json();
        document.getElementById('dbModeDisplay').textContent = models?.data?.[0]?.id || 'hermoresearch-ai';
      } catch {}
    } else {
      status.innerHTML = '<span class="status-dot offline"></span>连接失败 (' + res.status + ')';
    }
  } catch (err) {
    status.innerHTML = '<span class="status-dot offline"></span>无法连接';
  }
}

function saveSettings() {
  const base = document.getElementById('settingApiBase')?.value;
  if (base) localStorage.setItem('mia_api_base', base);
  // Reload API_BASE - since it's a const, we update the global reference in chat.js by reloading
  alert('设置已保存，将在下次刷新生效');
}

// ==================== GREETING ====================

function getGreeting() {
  const h = new Date().getHours();
  if (h < 6) return '晚上好';
  if (h < 11) return '早上好';
  if (h < 13) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

// ==================== INIT ====================

document.getElementById('greetingText').textContent = getGreeting();
renderSessions();
renderMarket();
renderSettingsTab('connection');
