'use strict';

const copy = {
  fa: {
    operations: 'میز عملیات ایکامرس', overview: 'نمای کلی', account: 'اکانت',
    all: 'همهٔ اکانت‌های مجاز', source: 'منبع داده', workbook: 'اکسل',
    demo: 'دموی ساختگی', cutoff: 'مقطع گزارش', month: 'ماه', day: 'روز', hour: 'ساعت',
    overlay: 'با ثبت‌های فرضی', retry: 'تلاش دوباره', metrics: 'شاخص‌های فروش',
    performance: 'عملکرد اکانت‌ها', queue: 'صف پیگیری', salesDesk: 'میز فروش و مدیریت داده',
    net: 'فروش خالص', target: 'هدف فروش', attainment: 'تحقق هدف', followUps: 'پرونده‌های باز',
    packs: 'بسته', unknown: 'نامشخص', loading: 'در حال دریافت داده…',
    unavailable: 'دریافت اطلاعات کامل نشد.', reload: 'نشست یا دسترسی تغییر کرده است. صفحه را دوباره باز کنید.',
    noPerformance: 'برای این محدوده دادهٔ عملکرد موجود نیست.',
    noCases: 'در این محدوده پرونده‌ای وجود ندارد.',
    reviewFirst: 'برای این مقطع صف آماده نیست. بررسی را از میز فروش اجرا کنید.',
    startDemo: 'دموی ساختگی را از میز فروش شروع کنید.',
    caseTitle: 'جزئیات پرونده', dismiss: 'بستن پنجره', evidence: 'شواهد',
    invalidEvidence: 'شاهد معتبر نیست', validEvidence: 'شاهد معتبر',
    discount: 'تخفیف مشاهده‌شده', cap: 'سقف مجاز', policy: 'سیاست تخفیف',
    adminOnly: 'نقش مدیر سیستم به تنظیمات دسترسی دارد. برای گزارش و پرونده‌ها از نقش کسب‌وکار استفاده کنید.',
    noEvidence: 'شاهدی در این پرونده ثبت نشده است.', next: 'اقدام پیشنهادی',
    approve: 'تأیید و ثبت ارجاع', saving: 'در حال ثبت تصمیم…', saved: 'ارجاع ثبت شد.',
    refreshCase: 'دریافت دوبارهٔ پرونده', referrals: 'ارجاع‌های ثبت‌شده',
    recheck: 'وضعیت را دوباره دریافت کنید تا نتیجهٔ آخرین درخواست مشخص شود.',
    open: 'نیازمند اقدام', needs_review: 'نیازمند شاهد', recovery_verified: 'رفع مشکل تأیید شد', closed: 'بسته شده',
  },
  en: {
    operations: 'Commerce operations', overview: 'Overview', account: 'Account',
    all: 'All permitted accounts', source: 'Data source', workbook: 'Workbook',
    demo: 'Synthetic demo', cutoff: 'Reporting cutoff', month: 'Month', day: 'Day', hour: 'Hour',
    overlay: 'Include hypothetical entries', retry: 'Retry', metrics: 'Sales metrics',
    performance: 'Account performance', queue: 'Follow-up queue', salesDesk: 'Sales desk and data management',
    net: 'Net sales', target: 'Sales target', attainment: 'Target attainment', followUps: 'Open cases',
    packs: 'packs', unknown: 'Unknown', loading: 'Loading data…',
    unavailable: 'Could not load the data.', reload: 'Your session or access changed. Reload the page.',
    noPerformance: 'No performance data for this selection.',
    noCases: 'There are no cases for this selection.',
    reviewFirst: 'The queue for this cutoff is unavailable. Run a review from the sales desk.',
    startDemo: 'Start the synthetic demo from the sales desk.',
    caseTitle: 'Case details', dismiss: 'Close dialog', evidence: 'Evidence',
    invalidEvidence: 'Evidence unverified', validEvidence: 'Evidence verified',
    discount: 'Observed discount', cap: 'Allowed limit', policy: 'Discount policy',
    adminOnly: 'The system administrator role can access settings. Use a business role for reports and cases.',
    noEvidence: 'This case has no recorded evidence.', next: 'Suggested action',
    approve: 'Approve and record referral', saving: 'Recording decision…', saved: 'Referral recorded.',
    refreshCase: 'Refresh case', referrals: 'Recorded referrals',
    recheck: 'Refresh the case to check the outcome of the last request.',
    open: 'Needs action', needs_review: 'Needs evidence', recovery_verified: 'Recovery verified', closed: 'Closed',
  },
};

const monthNames = { مهر: 'Mehr', آبان: 'Aban', آذر: 'Azar', دی: 'Dey', بهمن: 'Bahman', اسفند: 'Esfand' };
const accountNames = { 'ACC-DIGI': 'Digikala', 'ACC-OKALA': 'Okala', 'ACC-SNAPP': 'Snapp' };
const el = id => document.getElementById(id);
const dialog = el('case-dialog');
let language = 'fa';
let session;
let report;
let queue;
let dashboardError;
let dashboardLoading = false;
let dashboardRequest = 0;
let activeCase;
let caseRequest = 0;
let saving = false;

const t = key => copy[language][key];
const html = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[char]);
const accountName = id => (language === 'en' && accountNames[id]) || session.accounts[id] || id;
const monthName = name => (language === 'en' && monthNames[name]) || name;
const period = (net, target) => net != null && target != null && Number(target) > 0
  ? Number(net) / Number(target)
  : null;

function format(value, percent = false) {
  if (value == null || !Number.isFinite(Number(value))) return t('unknown');
  return new Intl.NumberFormat(language === 'fa' ? 'fa-IR' : 'en', {
    style: percent ? 'percent' : 'decimal',
    maximumFractionDigits: 1,
  }).format(Number(value));
}

function errorText(error) {
  if ([401, 403].includes(error.status)) return t('reload');
  return error.messageFromServer || t('unavailable');
}

async function api(action, fields = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (action !== 'start') headers['X-Active-Session'] = session.token;
  const response = await fetch('/api/' + action, {
    method: 'POST',
    headers,
    body: JSON.stringify(fields),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || !data) {
    const error = new Error('Stageflow request failed');
    error.status = response.status;
    error.messageFromServer = [data?.error, data?.request_id].filter(Boolean).join(' · ');
    throw error;
  }
  return data;
}

function options(select, entries, selected) {
  select.replaceChildren(...entries.map(([key, label]) => new Option(label, key, false, key === selected)));
}

function updateDays(preferred = Number(el('day').value)) {
  const days = session.months.find(month => month.name === el('month').value).days;
  options(el('day'), Array.from({ length: days }, (_, i) => [String(i + 1), format(i + 1)]),
    String(Math.max(1, Math.min(days, preferred))));
}

function updateFilterLabels() {
  if (!session) return;
  const accounts = Object.keys(session.accounts).map(id => [id, accountName(id)]);
  if (['manager', 'observer'].includes(session.role)) accounts.unshift(['all', t('all')]);
  options(el('account'), accounts, el('account').value || accounts[0][0]);
  options(el('month'), session.months.map(month => [month.name, monthName(month.name)]),
    el('month').value || 'بهمن');
  updateDays(el('day').value ? Number(el('day').value) : 15);
  options(el('hour'), Array.from({ length: 24 }, (_, hour) => [String(hour), format(hour)]),
    el('hour').value || '18');
}

function setLanguage() {
  document.documentElement.lang = language;
  document.documentElement.dir = language === 'fa' ? 'rtl' : 'ltr';
  document.title = 'Active | ' + t('operations');
  el('language').textContent = language === 'fa' ? 'English' : 'فارسی';
  el('language').lang = language === 'fa' ? 'en' : 'fa';
  document.querySelectorAll('[data-label]').forEach(node => {
    node.textContent = t(node.dataset.label);
  });
  updateFilterLabels();
  renderDashboard();
}

function scope() {
  return {
    account: el('account').value,
    dataset: el('dataset').value,
    month: el('month').value,
    day: Number(el('day').value),
    hour: Number(el('hour').value),
  };
}

function icon(name) {
  return `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

function metric(label, value, symbol) {
  return `<article class="metric"><div>${t(label)}${icon(symbol)}</div><strong>${value}</strong></article>`;
}

function packs(value) {
  return value == null ? t('unknown') : format(value) + ' ' + t('packs');
}

function statusName(item) {
  return t(item.status) || item.status_label || t('unknown');
}

function renderDashboard() {
  el('dashboard').hidden = !report;
  el('admin-link').hidden = session?.role !== 'admin';
  el('status').textContent = dashboardLoading ? t('loading') : dashboardError ? errorText(dashboardError) : '';
  if (session?.role === 'admin') el('status').textContent = t('adminOnly');
  el('retry').hidden = !dashboardError || dashboardLoading;
  if (!report) return;

  const openCount = queue?.available ? queue.cases.filter(item => item.status !== 'closed').length : null;
  el('metrics-data').innerHTML = [
    metric('net', packs(report.net), 'Package'),
    metric('target', packs(report.target), 'Store'),
    metric('attainment', format(report.attain ?? period(report.net, report.target), true), 'ChartNoAxesCombined'),
    metric('followUps', format(openCount), 'FolderCheck'),
  ].join('');

  el('account-performance').innerHTML = report.performance.length
    ? `<ul class="accounts">${report.performance.map(item => {
      const ratio = period(item.net, item.target);
      const name = html(accountName(item.account));
      return `<li><div class="account-row"><strong>${name}</strong><bdi>${format(ratio, true)}</bdi></div>
        <p class="muted"><bdi>${packs(item.net)}</bdi> / <bdi>${packs(item.target)}</bdi></p>
        ${ratio == null ? '' : `<progress max="1" value="${Math.max(0, Math.min(1, ratio))}" aria-label="${name}"></progress>`}</li>`;
    }).join('')}</ul>`
    : `<p class="muted">${t('noPerformance')}</p>`;

  if (!queue?.available || !queue.cases.length) {
    const message = queue?.available ? 'noCases' : scope().dataset === 'class-demo' ? 'startDemo' : 'reviewFirst';
    el('cases').innerHTML = `<p class="muted">${t(message)}</p>`;
    return;
  }
  el('cases').innerHTML = `<ul class="cases">${queue.cases.map(item => `<li class="case-row">
    <button type="button" data-case="${html(item.id)}"><bdi>${html(item.title)}</bdi></button>
    <span class="muted"><bdi>${html(accountName(item.account))}</bdi> · ${html(statusName(item))}</span>
  </li>`).join('')}</ul>`;
}

async function loadDashboard() {
  const request = ++dashboardRequest;
  dashboardLoading = true;
  dashboardError = null;
  report = queue = null;
  renderDashboard();

  try {
    if (!session) {
      session = await api('start');
      if (session.role === 'admin') return;
      updateFilterLabels();
      el('filters').hidden = false;
    }
    const selected = scope();
    const workbook = selected.dataset === 'workbook';
    el('cutoff').hidden = !workbook;
    el('overlay-filter').hidden = !workbook;
    const data = await Promise.all([
      api('report', { ...selected, overlay: workbook && el('overlay').checked }),
      api('cases', selected),
    ]);
    if (request === dashboardRequest) [report, queue] = data;
  } catch (error) {
    if (request === dashboardRequest) dashboardError = error;
  } finally {
    if (request === dashboardRequest) {
      dashboardLoading = false;
      renderDashboard();
    }
  }
}

function renderCase(detail) {
  const draft = detail.drafts.at(-1);
  el('case-title').textContent = detail.title;
  el('case-content').innerHTML = `
    <p class="muted"><bdi>${html(accountName(detail.account))}</bdi> · ${html(statusName(detail))}</p>
    <p><bdi>${html(detail.reason)}</bdi></p>
    <h3>${t('evidence')}</h3>
    ${detail.evidence.length ? `<ul class="evidence-list">${detail.evidence.map(item => `<li class="evidence">
      <strong>${t(item.valid ? 'validEvidence' : 'invalidEvidence')}</strong> · <bdi>${html(item.id)}</bdi>
      ${item.text ? `<p><bdi>${html(item.text)}</bdi></p>` : ''}
      ${item.percent == null ? '' : `<p>${t('discount')} <bdi>${format(Number(item.percent) / 100, true)}</bdi></p>`}
      ${item.cap == null ? '' : `<p>${t('cap')} <bdi>${format(Number(item.cap) / 100, true)}</bdi></p>`}
      ${item.policy_id ? `<p>${t('policy')} <bdi>${html(item.policy_id)}</bdi></p>` : ''}
    </li>`).join('')}</ul>` : `<p class="muted">${t('noEvidence')}</p>`}
    <div><h3>${t('next')}</h3><p><bdi>${html(draft?.edited || detail.next)}</bdi></p></div>
    ${detail.referrals.length ? `<section><h3>${t('referrals')}</h3>${detail.referrals.map(item =>
      `<div class="referral"><bdi>${html(item.id)}</bdi><p><bdi>${html(item.text)}</bdi></p></div>`
    ).join('')}</section>` : ''}
    ${detail.can_decide && draft?.status === 'validated'
      ? `<button type="button" id="approve" class="approve">${t('approve')}</button>`
      : ''}`;
  el('approve')?.addEventListener('click', () => approve(draft.id));
}

function refreshCaseButton() {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = t('refreshCase');
  button.onclick = () => openCase(activeCase);
  el('case-content').append(button);
  button.focus();
}

async function openCase(selection) {
  activeCase = selection;
  const request = ++caseRequest;
  el('case-title').textContent = t('caseTitle');
  el('case-status').textContent = t('loading');
  el('case-content').replaceChildren();
  if (!dialog.open) dialog.showModal();

  try {
    const detail = await api('case', selection);
    if (request !== caseRequest) return;
    el('case-status').textContent = '';
    renderCase(detail);
  } catch (error) {
    if (request !== caseRequest) return;
    el('case-status').textContent = errorText(error);
    refreshCaseButton();
  }
}

async function approve(draft) {
  if (saving) return;
  saving = true;
  el('approve').disabled = true;
  el('close-case').disabled = true;
  el('case-status').textContent = t('saving');

  try {
    const detail = await api('decide', { ...activeCase, draft, decision: 'approve' });
    renderCase(detail);
    el('case-status').textContent = t('saved');
  } catch (error) {
    el('approve')?.remove();
    el('case-status').textContent = errorText(error) + ' ' + t('recheck');
    refreshCaseButton();
  } finally {
    saving = false;
    el('close-case').disabled = false;
    if (document.activeElement === document.body) el('close-case').focus();
  }
}

el('language').addEventListener('click', () => {
  language = language === 'fa' ? 'en' : 'fa';
  setLanguage();
});
el('filters').addEventListener('submit', event => event.preventDefault());
el('filters').addEventListener('change', event => {
  if (event.target === el('month')) updateDays();
  void loadDashboard();
});
el('retry').addEventListener('click', loadDashboard);
el('cases').addEventListener('click', event => {
  const button = event.target.closest('[data-case]');
  if (button) void openCase({ ...scope(), id: button.dataset.case });
});
dialog.addEventListener('cancel', event => {
  if (saving) event.preventDefault();
});
dialog.addEventListener('close', () => {
  if (!dialog.open) caseRequest++;
});

setLanguage();
void loadDashboard();
