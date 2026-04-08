// ============================================================
// chat.js — SSE streaming client, tool_calls parser, multimodal
// Ported from polydata-insight's Svelte frontend to vanilla JS
// ============================================================

const API_BASE = localStorage.getItem('mia_api_base') || '';

// --- Tool call regex (from polydata-insight/frontend/src/lib/api/chat.ts) ---
const TOOL_CALL_REGEX = /<details\s+type="tool_calls"\s+([^>]*)>\s*<\/details>\s*/g;

const STEP_NAMES = {
  'classify_intent': '理解问题',
  'schema_discovery': '分析数据结构',
  'agent.reasoning':  '查询与分析'
};
const TOTAL_STEPS = 3;

// --- Parse <details type="tool_calls"> blocks from SSE content ---
function parseToolCalls(text) {
  const toolCalls = [];
  let remaining = text;
  let match;
  const re = new RegExp(TOOL_CALL_REGEX.source, 'g');
  while ((match = re.exec(text)) !== null) {
    const attrs = match[1];
    const name = (attrs.match(/name="([^"]*)"/) || [])[1] || '';
    const done = (attrs.match(/done="([^"]*)"/) || [])[1] === 'true';
    const args = ((attrs.match(/arguments="([^"]*)"/) || [])[1] || '').replace(/&quot;/g, '"');
    const result = ((attrs.match(/result="([^"]*)"/) || [])[1] || '').replace(/&quot;/g, '"');
    toolCalls.push({ name, done, arguments: args, result });
    remaining = remaining.replace(match[0], '');
  }
  return { toolCalls, remaining: remaining.trim() };
}

// --- SSE Streaming Chat ---
async function* streamChat(message, history = [], images = [], signal) {
  let userContent;
  if (images.length > 0) {
    const parts = images.map(url => ({ type: 'image_url', image_url: { url } }));
    parts.push({ type: 'text', text: message });
    userContent = parts;
  } else {
    userContent = message;
  }

  const messages = [...history, { role: 'user', content: userContent }];
  const res = await fetch(`${API_BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'hermoresearch-ai', messages, stream: true, temperature: 0.0 }),
    signal
  });

  if (!res.ok) {
    yield { type: 'error', error: `HTTP ${res.status}: ${res.statusText}` };
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) { yield { type: 'error', error: 'No response body' }; return; }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6).trim();
      if (data === '[DONE]') { yield { type: 'done' }; return; }

      try {
        const chunk = JSON.parse(data);
        const delta = chunk.choices?.[0]?.delta;
        const finishReason = chunk.choices?.[0]?.finish_reason;
        if (finishReason === 'stop') { yield { type: 'done' }; return; }

        if (delta?.content) {
          const content = delta.content;
          if (content.includes('<details type="tool_calls"')) {
            const { toolCalls, remaining } = parseToolCalls(content);
            for (const tc of toolCalls) yield { type: 'tool_call', toolCall: tc };
            if (remaining) yield { type: 'content', content: remaining };
          } else {
            yield { type: 'content', content };
          }
        }
      } catch { /* skip malformed JSON */ }
    }
  }
}

// --- ASR: Transcribe audio ---
async function transcribeAudio(audioBlob) {
  const formData = new FormData();
  formData.append('file', audioBlob, 'recording.webm');
  formData.append('model', 'whisper-1');
  const res = await fetch(`${API_BASE}/v1/audio/transcriptions`, { method: 'POST', body: formData });
  if (!res.ok) throw new Error(`ASR failed: ${res.status}`);
  const data = await res.json();
  return data.text || '';
}

// --- TTS: Synthesize speech ---
async function synthesizeSpeech(text, voice = 'zh-CN-XiaoxiaoNeural') {
  const res = await fetch(`${API_BASE}/v1/audio/speech`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input: text, voice })
  });
  if (!res.ok) throw new Error(`TTS failed: ${res.status}`);
  return res.blob();
}

// --- Simple Markdown renderer ---
function renderMarkdown(text) {
  if (!text) return '';
  let html = text
    // Code blocks
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code class="lang-${lang || 'text'}">${escHTML(code.trim())}</code></pre>`)
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Bold
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
    // Headers
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    // HR
    .replace(/^---$/gm, '<hr>')
    // Blockquote
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    // Tables
    .replace(/^\|(.+)\|$/gm, (match) => {
      const cells = match.split('|').filter(c => c.trim());
      if (cells.every(c => /^[\s-:]+$/.test(c))) return '<!--table-sep-->';
      return '<tr>' + cells.map(c => `<td>${c.trim()}</td>`).join('') + '</tr>';
    })
    // Strip VOICE_SUMMARY comments
    .replace(/<!-- VOICE_SUMMARY -->([\s\S]*?)<!-- \/VOICE_SUMMARY -->/g, '')
    // Unordered lists
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    // Ordered lists
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    // Paragraphs (double newline)
    .replace(/\n\n/g, '</p><p>')
    // Single newlines
    .replace(/\n/g, '<br>');

  // Wrap consecutive <tr> in <table>
  html = html.replace(/((?:<tr>[\s\S]*?<\/tr>\s*<!--table-sep-->\s*)+(?:<tr>[\s\S]*?<\/tr>\s*)+)/g, (block) => {
    const rows = block.replace(/<!--table-sep-->/g, '').trim();
    const parts = rows.split('</tr>').filter(r => r.trim());
    if (parts.length < 2) return `<table>${rows}</table>`;
    const header = parts[0] + '</tr>';
    const body = parts.slice(1).map(r => r.trim() ? r + '</tr>' : '').join('');
    return `<table><thead>${header.replace(/<td>/g, '<th>').replace(/<\/td>/g, '</th>')}</thead><tbody>${body}</tbody></table>`;
  });
  // Wrap consecutive <li> in <ul>
  html = html.replace(/((?:<li>[\s\S]*?<\/li>\s*)+)/g, '<ul>$1</ul>');

  return `<p>${html}</p>`;
}

// --- Render ToolStatus HTML ---
// Ordered list of pipeline steps (matches backend VISIBLE_STEPS)
const STEP_ORDER = ['classify_intent', 'schema_discovery', 'agent.reasoning'];
const STEP_ICONS = {
  'classify_intent':  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
  'schema_discovery': '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/></svg>',
  'agent.reasoning':  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>',
};

function renderToolStatus(toolCalls, streaming) {
  if (!toolCalls.length && !streaming) return '';

  // Build a lookup: name → toolCall
  const callMap = {};
  for (const tc of toolCalls) callMap[tc.name] = tc;

  const doneCount = toolCalls.filter(tc => tc.done).length;
  const allDone = doneCount >= TOTAL_STEPS;

  let rows = '';
  for (const stepName of STEP_ORDER) {
    const tc = callMap[stepName];
    const label = STEP_NAMES[stepName] || stepName;
    const icon = STEP_ICONS[stepName] || '';

    if (!tc) {
      // Step hasn't started yet
      if (allDone) continue; // don't show un-triggered steps after completion
      rows += `<div class="step-row pending">
        <span class="step-icon pending-icon">${icon}</span>
        <span class="step-row-label">${label}</span>
      </div>`;
    } else if (tc.done) {
      // Step completed
      rows += `<div class="step-row done">
        <svg class="step-icon done-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
        <span class="step-row-label">${label}</span>
      </div>`;
    } else {
      // Step in progress
      rows += `<div class="step-row active">
        <span class="step-icon"><span class="spinner-sm"></span></span>
        <span class="step-row-label">${label}</span>
      </div>`;
    }
  }

  const statusClass = allDone ? 'tool-steps all-done' : 'tool-steps';
  const summary = allDone
    ? `<div class="steps-summary done"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg> 分析完成</div>`
    : `<div class="steps-summary"><span class="step-progress">${doneCount}/${TOTAL_STEPS}</span></div>`;

  return `<div class="${statusClass}">${rows}${summary}</div>`;
}

// --- Extract voice-friendly text ---
function getVoiceText(content) {
  const match = content.match(/<!-- VOICE_SUMMARY -->([\s\S]*?)<!-- \/VOICE_SUMMARY -->/);
  if (match) return match[1].trim();
  return content
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\|[^\n]+\|/g, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[.*?\]\(.*?\)/g, '')
    .replace(/\[([^\]]+)\]\(.*?\)/g, '$1')
    .replace(/<[^>]+>/g, '')
    .replace(/0x[a-fA-F0-9]{4,}\.{0,3}[a-fA-F0-9]*/g, '')
    .replace(/\n{2,}/g, '\n')
    .trim();
}

// --- Helpers ---
function escHTML(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
