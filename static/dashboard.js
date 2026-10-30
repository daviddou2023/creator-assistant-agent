const state = { jobId: null, eventSource: null, creatorId: 'default_creator', result: null };
const nodes = ['plan', 'execute', 'replan', 'verify', 'report'];
const form = document.getElementById('reviewForm');
const statusEl = document.getElementById('serviceStatus');
const todoList = document.getElementById('todoList');
const eventLog = document.getElementById('eventLog');
const metricsBody = document.getElementById('metricsBody');
const commentSignals = document.getElementById('commentSignals');
const explanations = document.getElementById('explanations');
const newHypotheses = document.getElementById('newHypotheses');
const hypothesisList = document.getElementById('hypothesisList');
const reportView = document.getElementById('reportView');
const feedbackArea = document.getElementById('feedbackArea');
const feedbackStatus = document.getElementById('feedbackStatus');

function setStatus(value) { statusEl.textContent = value; }

function addLog(message) {
  const row = document.createElement('div');
  row.textContent = `${new Date().toLocaleTimeString()}  ${message}`;
  eventLog.prepend(row);
}

function selectedHypotheses() {
  return [...hypothesisList.querySelectorAll('input:checked')].map((input) => {
    const hypothesis = JSON.parse(input.dataset.hypothesis);
    return hypothesis;
  });
}

async function loadHypotheses() {
  const creatorId = form.elements.creator_id.value.trim() || 'default_creator';
  try {
    const response = await fetch(`/api/hypotheses?creator_id=${encodeURIComponent(creatorId)}`);
    const data = await response.json();
    hypothesisList.replaceChildren();
    if (!data.hypotheses.length) {
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.textContent = '暂无已确认的假设';
      hypothesisList.append(empty);
      return;
    }
    data.hypotheses.forEach((hypothesis) => {
      const label = document.createElement('label');
      label.className = 'hypothesis-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.dataset.hypothesis = JSON.stringify(hypothesis);
      const text = document.createElement('span');
      text.textContent = hypothesis.statement;
      label.append(checkbox, text);
      hypothesisList.append(label);
    });
  } catch (error) {
    hypothesisList.textContent = '无法加载历史假设';
  }
}

function resetView() {
  todoList.replaceChildren();
  eventLog.replaceChildren();
  metricsBody.replaceChildren();
  commentSignals.replaceChildren();
  explanations.replaceChildren();
  newHypotheses.replaceChildren();
  reportView.textContent = '';
  feedbackArea.hidden = true;
  feedbackStatus.textContent = '';
  document.getElementById('jobMeta').textContent = '';
}

function showTodos(todos) {
  todoList.replaceChildren();
  const list = Array.isArray(todos) ? todos : [];
  document.getElementById('taskCount').textContent = list.length ? `${list.length} 项` : '';
  list.forEach((todo) => {
    const row = document.createElement('li');
    const title = document.createElement('strong');
    title.textContent = todo.reason || todo.type;
    const detail = document.createElement('span');
    detail.textContent = [todo.type, ...(todo.keys || [])].join(' · ');
    const taskStatus = document.createElement('em');
    taskStatus.textContent = todo.status || 'pending';
    row.append(title, detail, taskStatus);
    todoList.append(row);
  });
}

function showMetrics(result) {
  const values = result.selected_metrics?.values || {};
  metricsBody.replaceChildren();
  const names = { views: '播放量', likes: '点赞量', shares: '转发量', favorites: '收藏量', coins: '投币量', danmaku: '弹幕量', reply: '平台评论量' };
  Object.entries(values).forEach(([key, value]) => {
    const row = document.createElement('tr');
    const name = document.createElement('th');
    const metric = document.createElement('td');
    name.textContent = names[key] || key;
    metric.textContent = Number(value).toLocaleString();
    row.append(name, metric);
    metricsBody.append(row);
  });
  Object.entries(result.selected_metrics?.derived || {}).forEach(([key, value]) => {
    const row = document.createElement('tr');
    const name = document.createElement('th');
    const metric = document.createElement('td');
    name.textContent = ({ like_rate: '点赞率', share_rate: '转发率', engagement_rate: '互动率' })[key] || key;
    metric.textContent = `${(Number(value) * 100).toFixed(2)}%`;
    row.append(name, metric);
    metricsBody.append(row);
  });
  Object.entries(result.selected_metrics?.growth || {}).forEach(([key, value]) => {
    const row = document.createElement('tr');
    const name = document.createElement('th');
    const metric = document.createElement('td');
    name.textContent = `${key} 增量`;
    metric.textContent = Number(value).toLocaleString();
    row.append(name, metric);
    metricsBody.append(row);
  });
  if (!Object.keys(values).length) metricsBody.innerHTML = '<tr><td class="muted">没有可展示的指标</td></tr>';

  const comments = result.comment_insights;
  if (!comments) return;
  const summary = document.createElement('p');
  summary.textContent = `评论样本 ${comments.total || 0} 条 · 正向 ${comments.sentiment?.positive || 0} · 中性 ${comments.sentiment?.neutral || 0} · 负向 ${comments.sentiment?.negative || 0}`;
  const keywords = document.createElement('p');
  keywords.textContent = `高频信号：${(comments.hot_keywords || []).map(([word, count]) => `${word} (${count})`).join('、') || '暂无'}`;
  commentSignals.replaceChildren(summary, keywords);
}

function showExplanations(result) {
  explanations.replaceChildren();
  (result.explanations || []).forEach((item) => {
    const article = document.createElement('article');
    article.className = 'finding';
    const heading = document.createElement('h3');
    heading.textContent = item.claim;
    const confidence = document.createElement('p');
    confidence.className = 'confidence';
    confidence.textContent = `置信度：${item.confidence || 'low'}`;
    const evidence = document.createElement('ul');
    (item.evidence || []).forEach((value) => {
      const li = document.createElement('li');
      li.textContent = value;
      evidence.append(li);
    });
    (item.counter_evidence || []).forEach((value) => {
      const li = document.createElement('li');
      li.textContent = `反向/缺失证据：${value}`;
      evidence.append(li);
    });
    const limits = document.createElement('p');
    limits.className = 'muted';
    limits.textContent = `限制：${(item.limitations || []).join('；') || '无额外说明'}`;
    article.append(heading, confidence, evidence, limits);
    explanations.append(article);
  });
  newHypotheses.replaceChildren();
  (result.hypotheses || []).forEach((item) => {
    const article = document.createElement('article');
    article.className = 'finding';
    const heading = document.createElement('h3');
    heading.textContent = item.statement;
    const scope = document.createElement('p');
    scope.textContent = `适用范围：${item.scope || '待确认'}`;
    const validation = document.createElement('p');
    validation.textContent = `验证方式：${item.validation || '待定义'} · 置信度：${item.confidence || 'low'}`;
    article.append(heading, scope, validation);
    newHypotheses.append(article);
  });
}

function connectStream(jobId) {
  state.eventSource?.close();
  const source = new EventSource(`/api/reviews/${jobId}/events`);
  state.eventSource = source;
  source.addEventListener('run_started', () => setStatus('分析中'));
  source.addEventListener('node_update', (event) => {
    const payload = JSON.parse(event.data);
    addLog(`完成步骤：${payload.node}`);
    if (payload.data?.todos) showTodos(payload.data.todos);
    if (payload.data?.selected_metrics || payload.data?.comment_insights) {
      showMetrics({ selected_metrics: payload.data.selected_metrics || {}, comment_insights: payload.data.comment_insights });
    }
    if (payload.data?.explanations) showExplanations(payload.data);
    if (payload.data?.report) reportView.textContent = payload.data.report;
  });
  source.addEventListener('completed', (event) => {
    const payload = JSON.parse(event.data);
    state.result = payload.result || {};
    setStatus('已完成');
    showTodos(state.result.todos);
    showMetrics(state.result);
    showExplanations(state.result);
    reportView.textContent = state.result.report || '';
    feedbackArea.hidden = false;
    addLog('复盘完成，等待你的反馈。');
  });
  source.addEventListener('error', (event) => {
    if (event.data) {
      const payload = JSON.parse(event.data);
      setStatus('失败');
      addLog(payload.error || '分析失败');
    } else if (statusEl.textContent !== '已完成') {
      setStatus('连接中断');
    }
  });
}

async function submitReview(payload) {
  const response = await fetch('/api/reviews', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  state.jobId = data.job_id;
  document.getElementById('jobMeta').textContent = `任务 ${data.job_id.slice(0, 8)}`;
  connectStream(data.job_id);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  resetView();
  setStatus('准备中');
  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  payload.days_after_publish = Number(payload.days_after_publish || 30);
  payload.max_comments = Number(payload.max_comments || 50);
  payload.selected_hypotheses = selectedHypotheses();
  try {
    await submitReview(payload);
  } catch (error) {
    setStatus('失败');
    addLog(error.message || String(error));
  }
});

form.elements.creator_id.addEventListener('change', loadHypotheses);
document.getElementById('refreshHypotheses').addEventListener('click', loadHypotheses);

document.getElementById('confirmReport').addEventListener('click', async () => {
  if (!state.jobId) return;
  feedbackStatus.textContent = '正在保存确认结果…';
  const response = await fetch(`/api/reviews/${state.jobId}/feedback`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ satisfied: true })
  });
  const data = await response.json();
  feedbackStatus.textContent = response.ok ? '已确认，假设和证据已写入经验库。' : (data.error || '保存失败');
  if (response.ok) loadHypotheses();
});

document.getElementById('rerunFeedback').addEventListener('click', async () => {
  if (!state.jobId) return;
  const correction = document.getElementById('correction').value.trim();
  if (!correction) {
    feedbackStatus.textContent = '请先填写需要纠正或补充的内容。';
    return;
  }
  feedbackStatus.textContent = '正在按反馈重新分析…';
  try {
    const response = await fetch(`/api/reviews/${state.jobId}/feedback`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ correction })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '无法重新分析');
    state.jobId = data.job_id;
    resetView();
    setStatus('重新分析中');
    document.getElementById('jobMeta').textContent = `任务 ${data.job_id.slice(0, 8)}`;
    connectStream(data.job_id);
  } catch (error) {
    feedbackStatus.textContent = error.message || String(error);
  }
});

loadHypotheses();
