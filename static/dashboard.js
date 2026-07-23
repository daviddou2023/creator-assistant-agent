const nodeNames = [
  'retrieve_memory',
  'collect_data',
  'summarize_metrics',
  'analyze_comments',
  'data_analyst',
  'infer_content',
  'recommend',
  'plan_review',
  'render_report',
  'store_memory'
];

const state = {
  jobId: null,
  threadId: null,
  eventSource: null,
  dashboardData: null,
  report: '',
  plan: null,
  lastStatus: 'Idle'
};

const form = document.getElementById('reviewForm');
const eventLog = document.getElementById('eventLog');
const nodeList = document.getElementById('nodeList');
const cards = document.getElementById('cards');
const reportView = document.getElementById('reportView');
const planView = document.getElementById('planView');
const planNotes = document.getElementById('planNotes');
const jobMeta = document.getElementById('jobMeta');
const serviceStatus = document.getElementById('serviceStatus');
const approveBtn = document.getElementById('approveBtn');
const rejectBtn = document.getElementById('rejectBtn');
const retentionCanvas = document.getElementById('retentionChart');
const trendCanvas = document.getElementById('trendChart');
const sentimentCanvas = document.getElementById('sentimentChart');

let nodeState = {};

function initNodeList() {
  nodeList.innerHTML = '';
  nodeNames.forEach((name) => {
    const item = document.createElement('li');
    item.textContent = name;
    item.dataset.node = name;
    nodeList.appendChild(item);
  });
}

function setStatus(text) {
  state.lastStatus = text;
  serviceStatus.textContent = text;
}

function log(message) {
  const line = document.createElement('div');
  line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
  eventLog.prepend(line);
}

function updateNode(node, status) {
  nodeState[node] = status;
  document.querySelectorAll('#nodeList li').forEach((item) => {
    if (item.dataset.node === node) {
      item.classList.remove('done', 'active');
      item.classList.add(status);
    }
  });
}

function renderCards(data) {
  if (!data) return;
  const entries = [
    ['阅读量', data.cards.views],
    ['点赞量', data.cards.likes],
    ['转发量', data.cards.shares],
    ['评论量', data.cards.comments],
    ['点赞率', formatPercent(data.cards.like_rate)],
    ['转发率', formatPercent(data.cards.share_rate)],
    ['评论率', formatPercent(data.cards.comment_rate)]
  ];
  cards.innerHTML = entries.map(([label, value]) => `
    <div class="card">
      <div class="label">${label}</div>
      <div class="value">${value}</div>
    </div>
  `).join('');
}

function renderReport(text) {
  reportView.textContent = text || '';
}

function renderPlan(plan) {
  state.plan = plan;
  if (!plan) {
    planView.textContent = '';
    planNotes.value = '';
    return;
  }
  planView.textContent = JSON.stringify(plan, null, 2);
  const recommendations = Array.isArray(plan.recommendations) ? plan.recommendations.join('\n') : '';
  planNotes.value = recommendations;
}

function renderCharts(data) {
  if (!data) return;
  drawRetentionChart(retentionCanvas, data.retention_curve || []);
  drawTrendChart(trendCanvas, data.trend_points || []);
  drawBarChart(sentimentCanvas, data.sentiment || {});
}

function formatPercent(value) {
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function drawAxes(ctx, width, height, padding) {
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding, padding);
  ctx.lineTo(padding, height - padding);
  ctx.lineTo(width - padding, height - padding);
  ctx.stroke();
}

function drawLineSeries(ctx, points, color, width, height, padding, maxValue) {
  if (!points.length) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = padding + (index * (width - padding * 2)) / Math.max(points.length - 1, 1);
    const y = height - padding - (point.value / Math.max(maxValue, 1)) * (height - padding * 2);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawRetentionChart(canvas, points) {
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  const padding = 40;
  ctx.clearRect(0, 0, width, height);
  drawAxes(ctx, width, height, padding);
  const maxValue = 1;
  drawLineSeries(ctx, points, '#38bdf8', width, height, padding, maxValue);
  ctx.fillStyle = '#94a3b8';
  ctx.fillText('0%', 8, height - padding);
  ctx.fillText('100%', 8, padding + 4);
}

function drawTrendChart(canvas, points) {
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  const padding = 40;
  ctx.clearRect(0, 0, width, height);
  drawAxes(ctx, width, height, padding);
  const maxValue = Math.max(...points.flatMap((p) => [p.views || 0, p.likes || 0, p.shares || 0]), 1);
  drawLineSeries(ctx, points.map((p) => ({ ...p, value: p.views })), '#60a5fa', width, height, padding, maxValue);
  drawLineSeries(ctx, points.map((p) => ({ ...p, value: p.likes })), '#34d399', width, height, padding, maxValue);
  drawLineSeries(ctx, points.map((p) => ({ ...p, value: p.shares })), '#f59e0b', width, height, padding, maxValue);
}

function drawBarChart(canvas, sentiment) {
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  const padding = 40;
  ctx.clearRect(0, 0, width, height);
  drawAxes(ctx, width, height, padding);
  const items = [
    ['正向', sentiment.positive || 0, '#22c55e'],
    ['中性', sentiment.neutral || 0, '#64748b'],
    ['负向', sentiment.negative || 0, '#ef4444']
  ];
  const maxValue = Math.max(...items.map((item) => item[1]), 1);
  const barWidth = (width - padding * 2) / items.length - 20;
  items.forEach((item, index) => {
    const value = item[1];
    const barHeight = ((height - padding * 2) * value) / maxValue;
    const x = padding + index * ((width - padding * 2) / items.length) + 10;
    const y = height - padding - barHeight;
    ctx.fillStyle = item[2];
    ctx.fillRect(x, y, barWidth, barHeight);
    ctx.fillStyle = '#e2e8f0';
    ctx.fillText(`${item[0]} ${value}`, x, y - 8);
  });
}

async function startReview(payload) {
  setStatus('Starting');
  const response = await fetch('/api/reviews', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const data = await response.json();
  state.jobId = data.job_id;
  state.threadId = data.thread_id;
  jobMeta.textContent = `job ${data.job_id}`;
  connectStream(data.job_id);
  return data;
}

function connectStream(jobId) {
  if (state.eventSource) {
    state.eventSource.close();
  }
  const source = new EventSource(`/api/reviews/${jobId}/events`);
  state.eventSource = source;

  source.addEventListener('run_started', () => setStatus('Running'));
  source.addEventListener('run_resumed', () => setStatus('Resuming'));
  source.addEventListener('node_update', (event) => handleEvent(JSON.parse(event.data)));
  source.addEventListener('dashboard_update', (event) => handleEvent(JSON.parse(event.data)));
  source.addEventListener('interrupted', (event) => handleInterrupted(JSON.parse(event.data)));
  source.addEventListener('completed', (event) => handleCompleted(JSON.parse(event.data)));
  source.addEventListener('rejected', (event) => handleCompleted(JSON.parse(event.data)));
  source.addEventListener('error', (event) => handleError(JSON.parse(event.data)));
  source.addEventListener('heartbeat', () => setStatus(state.lastStatus || 'Waiting'));
  source.onerror = () => {
    if (!['Completed', 'Rejected'].includes(state.lastStatus)) {
      setStatus('Connection lost');
    }
  };
}

function handleEvent(event) {
  log(`${event.node || event.type}: update`);
  if (event.node) {
    updateNode(event.node, 'active');
    setTimeout(() => updateNode(event.node, 'done'), 300);
  }
  if (event.data && event.data.dashboard_data) {
    state.dashboardData = event.data.dashboard_data;
    renderCards(state.dashboardData);
    renderCharts(state.dashboardData);
  }
  if (event.data && event.data.report) {
    state.report = event.data.report;
    renderReport(state.report);
  }
}

function handleInterrupted(event) {
  setStatus('Waiting for approval');
  updateNode('plan_review', 'active');
  state.plan = event.plan;
  renderPlan(event.plan);
  log('Plan interrupted and waiting for approval.');
  if (event.plan && event.plan.resume_payload_example) {
    log('Resume payload example available.');
  }
}

function handleCompleted(event) {
  setStatus(event.type === 'rejected' ? 'Rejected' : 'Completed');
  if (event.result) {
    if (event.result.dashboard_data) {
      state.dashboardData = event.result.dashboard_data;
      renderCards(state.dashboardData);
      renderCharts(state.dashboardData);
    }
    if (event.result.report) {
      state.report = event.result.report;
      renderReport(state.report);
    }
    if (event.result.execution_plan) {
      renderPlan(event.result.execution_plan);
    }
    if (event.result.plan_approved !== undefined) {
      log(`plan_approved = ${event.result.plan_approved}`);
    }
  }
  log(`Job finished with status: ${event.type}`);
}

function handleError(event) {
  setStatus('Failed');
  log(event.error || 'Unknown error');
}

function normalizePlanNotes(text) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  initNodeList();
  nodeState = {};
  eventLog.innerHTML = '';
  renderPlan(null);
  renderReport('');
  cards.innerHTML = '';
  drawRetentionChart(retentionCanvas, []);
  drawTrendChart(trendCanvas, []);
  drawBarChart(sentimentCanvas, {});

  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  payload.memory_enabled = formData.get('memory_enabled') === 'on';
  payload.use_llm = formData.get('use_llm') === 'on';
  payload.require_plan_approval = formData.get('require_plan_approval') === 'on';
  payload.days_after_publish = Number(payload.days_after_publish || 7);
  payload.max_comments = Number(payload.max_comments || 50);
  payload.top_liked_comments_limit = Number(payload.top_liked_comments_limit || 5);
  if (!payload.thread_id) delete payload.thread_id;

  try {
    await startReview(payload);
  } catch (error) {
    setStatus('Failed');
    log(error.message || String(error));
  }
});

approveBtn.addEventListener('click', async () => {
  if (!state.jobId) return;
  const recommendations = normalizePlanNotes(planNotes.value);
  const payload = {
    resume_payload: {
      approved: true,
      recommendations,
      review_notes: 'Dashboard approved the plan.'
    }
  };
  await fetch(`/api/reviews/${state.jobId}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  setStatus('Resuming');
});

rejectBtn.addEventListener('click', async () => {
  if (!state.jobId) return;
  await fetch(`/api/reviews/${state.jobId}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      resume_payload: {
        approved: false,
        review_notes: 'Dashboard rejected the plan.'
      }
    })
  });
  setStatus('Rejected');
});

initNodeList();
drawRetentionChart(retentionCanvas, []);
drawTrendChart(trendCanvas, []);
drawBarChart(sentimentCanvas, {});
