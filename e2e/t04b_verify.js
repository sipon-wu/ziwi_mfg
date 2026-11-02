// t04b_verify.js — T04b 验收（真实后端，无 mock）
// 前置：
//   python e2e/t04b_fixture.py snapshot     （先快照）
//   后端 8000（backend/.venv）+ 前端 5173
// 覆盖：
//   出库执行 6 条 / 点检执行 6 条 / 三页两视口无横溢 / 双击 50ms 内只 1 次 POST
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173';
const SHOT = path.join(__dirname, 'screenshots', 't04b');
if (!fs.existsSync(SHOT)) fs.mkdirSync(SHOT, { recursive: true });

const STAMP = Date.now().toString().slice(-6);
const ORDER_A = `T04B-A-${STAMP}`;
const ORDER_B = `T04B-B-${STAMP}`;
const EQ_CODE = 'E2E-EQ-MT';
const EQ_ID = 14;
const TASK_ID = 11;

// 3 行：5 / 3 / 2，物料各自有 1000 可用（warehouse 1）
const LINES_A = [
  { line_no: 1, material_id: 329, material_code: 'UI-B-829866', required_qty: 5, unit: '个' },
  { line_no: 2, material_id: 327, material_code: 'UI-B-497985', required_qty: 3, unit: '个' },
  { line_no: 3, material_id: 323, material_code: 'MC-B-1101185236', required_qty: 2, unit: '个' },
];
const LINES_B = [
  { line_no: 1, material_id: 323, material_code: 'MC-B-1101185236', required_qty: 2, unit: '个' },
];

const results = [];
function rec(id, name, status, detail) {
  results.push({ id, name, status, detail });
  console.log(`[${status}] ${id} ${name} — ${detail}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 1×1 红点 PNG（拍照用）
const PNG_1PX = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', (e) => errs.push('[pageerror] ' + e.message));

  // 允许在页面内直接调后端（造夹具 / 回查落库），token 取自 localStorage
  const api = (method, url, body) => page.evaluate(
    async ({ method, url, body }) => {
      const token = localStorage.getItem('access_token');
      const tenant = localStorage.getItem('tenant_id');
      const res = await fetch(`/api/v1${url}`, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(tenant ? { 'X-Tenant-Id': tenant } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      const json = await res.json().catch(() => ({}));
      return { status: res.status, data: json.data ?? json, message: json.message };
    },
    { method, url, body },
  );

  // ── 登录 ──
  try {
    await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle', timeout: 30000 });
    await page.fill('input[placeholder="请输入用户名"]', 'mfg_admin');
    await page.fill('input[placeholder="请输入密码"]', 'admin123');
    await page.click('button[type="submit"]');
    await sleep(2500);
    const token = await page.evaluate(() => localStorage.getItem('access_token'));
    rec('G0', '登录 mfg_admin', token ? 'PASS' : 'FAIL', `token=${!!token}`);
  } catch (e) {
    rec('G0', '登录 mfg_admin', 'FAIL', e.message.slice(0, 160));
  }

  // ── 造夹具：两张出库单 ──
  let orderA = 0;
  let orderB = 0;
  try {
    const a = await api('POST', '/wms/issue-orders', {
      issue_no: ORDER_A, issue_type: 'production', warehouse_id: 1, recipient: 'T04B',
      items: LINES_A.map((l) => ({
        line_no: l.line_no, material_id: l.material_id,
        required_qty: l.required_qty, unit: l.unit,
      })),
    });
    const b = await api('POST', '/wms/issue-orders', {
      issue_no: ORDER_B, issue_type: 'production', warehouse_id: 1, recipient: 'T04B',
      items: LINES_B.map((l) => ({
        line_no: l.line_no, material_id: l.material_id,
        required_qty: l.required_qty, unit: l.unit,
      })),
    });
    orderA = a.data?.id || 0;
    orderB = b.data?.id || 0;
    rec('G1', '造夹具（2 张出库单）', orderA && orderB ? 'PASS' : 'FAIL',
      `${ORDER_A}=${orderA} status=${a.status}, ${ORDER_B}=${orderB} status=${b.status}`);
  } catch (e) {
    rec('G1', '造夹具（2 张出库单）', 'FAIL', e.message.slice(0, 160));
  }

  /* ================================================================ *
   * 出库执行（单 A：3 行，发第 1 行后差额结案）
   * ================================================================ */

  // 取单 A 的行 id（用于定位 DOM）
  const detailA = await api('GET', `/wms/issue-orders/scan?code=${encodeURIComponent(ORDER_A)}`);
  const linesA = detailA.data?.lines || [];
  const lineIdsA = {};
  for (const l of linesA) lineIdsA[l.line_no] = l.item_id;

  try {
    await page.goto(`${BASE}/#/wms/issue-orders/${orderA}/execute`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1800);

    // W1 首行高亮 + 默认实发 = 需求
    const activeSel = await page.locator('.ioe-line--active').first().getAttribute('data-line-item');
    const firstInput = await page.locator(`.ioe-line[data-line-item="${lineIdsA[1]}"] .ioe-line__input`).inputValue();
    const w1 = Number(activeSel) === Number(lineIdsA[1]) && firstInput === '5';
    await page.screenshot({ path: path.join(SHOT, 'W1_loaded.png') });
    rec('W1', '打开即高亮首行 + 实发默认=需求', w1 ? 'PASS' : 'FAIL',
      `active=${activeSel} 期望=${lineIdsA[1]}; 第1行默认实发=${firstInput} 期望=5`);

    // W2 扫物料码 → 自动定位并高亮第 2 行
    await page.locator('.ioe-scan input').fill(LINES_A[1].material_code);
    await page.locator('.ioe-scan .ziwi-scan-field__btn').click();
    await sleep(600);
    const activeSel2 = await page.locator('.ioe-line--active').first().getAttribute('data-line-item');
    const hint = await page.locator('.ioe-scan-hint').innerText().catch(() => '');
    const focusLine = await page.evaluate(() => {
      const el = document.activeElement;
      const host = el?.closest?.('.ioe-line');
      return host ? host.getAttribute('data-line-item') : null;
    });
    const w2 = Number(activeSel2) === Number(lineIdsA[2]) && hint.includes('第 2 行') && Number(focusLine) === Number(lineIdsA[2]);
    await page.screenshot({ path: path.join(SHOT, 'W2_scan_located.png') });
    rec('W2', '扫物料码 → 自动定位并高亮对应行', w2 ? 'PASS' : 'FAIL',
      `active=${activeSel2} 期望=${lineIdsA[2]}; hint="${hint}"; 焦点行=${focusLine}`);

    // W3 单行提交 → 行变「已发」+ 单据 issued_qty 累计
    const beforeOrder = await api('GET', `/wms/issue-orders/${orderA}`);
    await page.locator(`.ioe-line[data-line-item="${lineIdsA[1]}"] .ioe-line__btn`).click();
    await sleep(2000);
    const lineTag = await page.locator(`.ioe-line[data-line-item="${lineIdsA[1]}"] .ioe-line__tag`).innerText();
    const afterOrder = await api('GET', `/wms/issue-orders/${orderA}`);
    const w3 = lineTag.includes('已发')
      && Number(afterOrder.data?.issued_qty) === 5
      && Number(beforeOrder.data?.issued_qty) === 0
      && afterOrder.data?.status === 'partially_issued';
    await page.screenshot({ path: path.join(SHOT, 'W3_line_issued.png') });
    rec('W3', '单行提交 → 行变已发 + 单据累计', w3 ? 'PASS' : 'FAIL',
      `行状态="${lineTag}"; 单据 issued_qty ${beforeOrder.data?.issued_qty}→${afterOrder.data?.issued_qty}; status=${afterOrder.data?.status}`);

    // W4 差额结案：确认单重述「第 N 行欠 X，结案后不可补拣」
    await page.locator('.ziwi-actionbar__btn--primary').click();
    await sleep(700);
    const sheetVisible = await page.locator('.ziwi-confirm').isVisible().catch(() => false);
    const consequence = sheetVisible
      ? await page.locator('.ziwi-confirm__consequence').innerText() : '';
    const objectLabel = sheetVisible
      ? await page.locator('.ziwi-confirm__object').innerText() : '';
    await page.screenshot({ path: path.join(SHOT, 'W4_short_confirm.png') });
    const w4 = sheetVisible
      && consequence.includes('第 2 行欠 3')
      && consequence.includes('第 3 行欠 2')
      && consequence.includes('结案后不可补拣')
      && objectLabel.includes(ORDER_A);
    rec('W4', '差额结案确认单重述欠发行与不可补拣', w4 ? 'PASS' : 'FAIL',
      `sheet=${sheetVisible} object="${objectLabel}" consequence="${consequence}"`);

    // W5 确认 → 回执带差异摘要
    await page.locator('.ziwi-confirm__btn--ok').click();
    await sleep(2200);
    const receiptVisible = await page.locator('.ziwi-receipt').isVisible().catch(() => false);
    const docNo = receiptVisible ? await page.locator('.ziwi-receipt__docno-value').innerText() : '';
    const qtys = receiptVisible
      ? (await page.locator('.ziwi-receipt__qtys').innerText()).replace(/\n/g, ' | ') : '';
    const extra = receiptVisible
      ? (await page.locator('.ziwi-receipt__extra').innerText()).replace(/\n/g, ' | ') : '';
    const finalA = await api('GET', `/wms/issue-orders/${orderA}`);
    await page.screenshot({ path: path.join(SHOT, 'W5_short_receipt.png') });
    const w5 = receiptVisible
      && docNo.trim() === ORDER_A
      && /实发合计\s*\|?\s*5/.test(qtys)
      && /2 行有差异，合计 5/.test(extra)
      && extra.includes('第 2 行欠 3')
      && finalA.data?.status === 'issued'
      && (finalA.data?.short_closed === 1 || finalA.data?.short_closed === true);
    rec('W5', '结案回执：单号 + 实发合计 + 差异摘要', w5 ? 'PASS' : 'FAIL',
      `receipt=${receiptVisible} docNo=${docNo.trim()} qtys="${qtys}" extra="${extra}" status=${finalA.data?.status} short_closed=${finalA.data?.short_closed}`);
  } catch (e) {
    rec('W1-W5', '出库执行（单 A）', 'FAIL', e.message.slice(0, 220));
    await page.screenshot({ path: path.join(SHOT, 'W_fail.png') }).catch(() => {});
  }

  /* ================================================================ *
   * 出库执行（单 B：1 行 → 发齐自动 issued；顺带双击幂等）
   * ================================================================ */
  const detailB = await api('GET', `/wms/issue-orders/scan?code=${encodeURIComponent(ORDER_B)}`);
  const lineIdsB = (detailB.data?.lines || []).map((l) => l.item_id);
  try {
    const issuePosts = [];
    page.on('request', (req) => {
      if (req.method() === 'POST' && /\/issue-order-items\/\d+\/issue$/.test(req.url())) {
        issuePosts.push({ at: Date.now(), url: req.url() });
      }
    });

    await page.goto(`${BASE}/#/wms/issue-orders/${orderB}/execute`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1500);
    // 换单前先关掉上一张单的回执弹层（它 lock-scroll 且盖住页面）
    const closeBtn = page.locator('.ziwi-receipt__close');
    if (await closeBtn.isVisible().catch(() => false)) {
      await closeBtn.click();
      await sleep(400);
    }
    const defaultQty = await page.locator('.ioe-line__input').first().inputValue();

    // 50ms 内连点两次（同一个宏任务里派发两个 click）
    await page.evaluate(() => {
      const btn = document.querySelector('.ioe-line__btn');
      btn.click();
      btn.click();
    });
    await sleep(2500);
    const gap = issuePosts.length > 1 ? issuePosts[1].at - issuePosts[0].at : -1;
    const b1 = issuePosts.length === 1 && defaultQty === '2';
    rec('W6', '双击提交（50ms 内）同一 POST 只 1 次', b1 ? 'PASS' : 'FAIL',
      `默认实发=${defaultQty} 期望=2; POST 次数=${issuePosts.length} 间隔=${gap}ms`);

    const receiptB = await page.locator('.ziwi-receipt').isVisible().catch(() => false);
    const extraB = receiptB
      ? (await page.locator('.ziwi-receipt__extra').innerText()).replace(/\n/g, ' | ') : '';
    const finalB = await api('GET', `/wms/issue-orders/${orderB}`);
    await page.screenshot({ path: path.join(SHOT, 'W6_auto_issued.png') });
    const b2 = finalB.data?.status === 'issued' && /全部行已发齐/.test(extraB);
    rec('W7', '全部发完 → 单据自动 issued + 回执', b2 ? 'PASS' : 'FAIL',
      `status=${finalB.data?.status} issued_qty=${finalB.data?.issued_qty} receipt=${receiptB} extra="${extraB}"`);
  } catch (e) {
    rec('W6-W7', '出库执行（单 B）', 'FAIL', e.message.slice(0, 220));
  }

  /* ================================================================ *
   * 点检执行
   * ================================================================ */
  try {
    await page.goto(`${BASE}/#/equipment/tasks`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1200);
    await page.locator('.et-scan input').fill(EQ_CODE);
    await page.locator('.et-scan .ziwi-scan-field__btn').click();
    await sleep(1800);
    const taskCount = await page.locator('.et-task').count();
    const eqName = await page.locator('.et-eq__name').innerText().catch(() => '');
    await page.screenshot({ path: path.join(SHOT, 'M1_equipment_tasks.png') });
    const m1 = taskCount > 0 && eqName.includes('E2E');
    rec('M1', '扫设备码 → 该设备任务清单', m1 ? 'PASS' : 'FAIL',
      `equipment="${eqName}" 任务=${taskCount}`);

    // 0 条任务的空态：换一台没有任务的设备验证（empty_kind='no_task'）
    const emptyEq = 'MC-002';
    await page.locator('.et-scan input').fill(emptyEq);
    await page.locator('.et-scan .ziwi-scan-field__btn').click();
    await sleep(1500);
    const emptyShown = await page.locator('.ziwi-state-view--empty-true').isVisible().catch(() => false);
    const emptyText = emptyShown ? await page.locator('.ziwi-state-view__title').innerText() : '';
    const emptyBtn = emptyShown ? await page.locator('.ziwi-state-view__btn').innerText() : '';
    await page.screenshot({ path: path.join(SHOT, 'M2_empty.png') });
    rec('M2', '0 条任务 → 空态 + 新建保养计划入口', emptyShown && emptyBtn.includes('新建') ? 'PASS' : 'FAIL',
      `equipment=${emptyEq} empty=${emptyShown} title="${emptyText}" action="${emptyBtn}"`);

    // 进执行页
    await page.goto(`${BASE}/#/equipment/maintenance-tasks/${TASK_ID}/execute`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1500);

    // 开工 → 设备状态 maintenance
    const beforeStart = await api('GET', `/equipment/${EQ_ID}`);
    await page.locator('.ziwi-actionbar__btn--primary').click();
    await sleep(2000);
    const duringStart = await api('GET', `/equipment/${EQ_ID}`);
    const statusText = await page.locator('.mex-head .ziwi-state').innerText().catch(() => '');

    // 无点检项 → 模板生成 3 项
    const templateBtn = page.locator('.ziwi-state-view__btn').first();
    const hasTemplate = await templateBtn.isVisible().catch(() => false);
    if (hasTemplate) await templateBtn.click();
    await sleep(600);
    const itemCount = await page.locator('.mex-item').count();

    // 3 项三态各一：正常 / 异常（带描述+照片）/ 不适用
    const items = page.locator('.mex-item');
    await items.nth(0).locator('.mex-verdict--normal').click();
    await items.nth(1).locator('.mex-verdict--abnormal').click();
    await sleep(300);
    await items.nth(1).locator('.mex-abnormal__input').fill('皮带打滑、有异响');
    await items.nth(1).locator('.mex-photo-add__input').setInputFiles({
      name: 'belt.png', mimeType: 'image/png', buffer: PNG_1PX,
    });
    await sleep(800);
    const photoCount = await items.nth(1).locator('.mex-photo img').count();
    await items.nth(2).locator('.mex-verdict--na').click();
    await sleep(300);
    await page.screenshot({ path: path.join(SHOT, 'M3_items.png') });

    const verdicts = await page.locator('.mex-item__state').allInnerTexts();
    const m3 = itemCount === 3 && verdicts[0].includes('正常') && verdicts[1].includes('异常')
      && verdicts[2].includes('不适用');
    rec('M3', '点检 3 项（正常/异常/不适用 各一）', m3 ? 'PASS' : 'FAIL',
      `模板=${hasTemplate} 项数=${itemCount} 判定=${JSON.stringify(verdicts.map((v) => v.trim()))}`);
    rec('M4', '异常项填描述后可拍照', photoCount > 0 ? 'PASS' : 'FAIL',
      `照片数=${photoCount}（Canvas 640/JPEG .6 → data URL）`);

    // 提交并完工
    await page.locator('.ziwi-actionbar__btn--primary').click();
    await sleep(3000);
    const receiptVisible = await page.locator('.ziwi-receipt').isVisible().catch(() => false);
    const docNo = receiptVisible ? await page.locator('.ziwi-receipt__docno-value').innerText() : '';
    const qtys = receiptVisible
      ? (await page.locator('.ziwi-receipt__qtys').innerText()).replace(/\n/g, ' | ') : '';
    const extra = receiptVisible
      ? (await page.locator('.ziwi-receipt__extra').innerText()).replace(/\n/g, ' | ') : '';
    await page.screenshot({ path: path.join(SHOT, 'M5_receipt.png') });

    const afterTask = await api('GET', `/maintenance-tasks/${TASK_ID}`);
    const afterEq = await api('GET', `/equipment/${EQ_ID}`);
    const m5 = receiptVisible && /3 项已点检，1 项异常/.test(extra) && /已生成安灯 #\d+/.test(extra);
    rec('M5', '提交并完工回执（3 项已点检，1 项异常，安灯 #id）', m5 ? 'PASS' : 'FAIL',
      `receipt=${receiptVisible} docNo=${docNo.trim()} qtys="${qtys}" extra="${extra}"`);

    // 开工后设备必须是 maintenance（不依赖异常分支）
    const m6a = beforeStart.data?.status === 'running' && duringStart.data?.status === 'maintenance'
      && afterTask.data?.status === 'completed';
    rec('M6a', '开工把设备置 maintenance，完工把任务置 completed', m6a ? 'PASS' : 'FAIL',
      `开工前=${beforeStart.data?.status} 开工后=${duringStart.data?.status} 任务=${afterTask.data?.status}（头部="${statusText.trim()}"）`);

    // ⚠️ 有异常项时安灯会把设备置 fault（后端 AndonService._link_on_create 的既定语义），
    //    所以"完工后 running"只在**无异常**路径成立。这里如实记录本次的终态。
    rec('M6b', '有异常项 → 安灯联动把设备置 fault（已知设计语义）', afterEq.data?.status === 'fault' ? 'PASS' : 'FAIL',
      `完工后设备=${afterEq.data?.status}（异常 1 项 → 开安灯 → 置 fault）`);

    // 无异常路径：新建一张任务，3 项全「正常」，完工后设备应回到 running
    const taskB = await api('POST', '/maintenance-tasks', {
      equipment_id: EQ_ID, task_type: 'inspection', description: 'T04B 无异常路径', priority: 0,
    });
    const taskBId = taskB.data?.id || 0;
    await page.goto(`${BASE}/#/equipment/maintenance-tasks/${taskBId}/execute`, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(1500);
    await page.locator('.ziwi-actionbar__btn--primary').click(); // 开工
    await sleep(2000);
    const afterStartB = await api('GET', `/equipment/${EQ_ID}`);
    const tplB = page.locator('.ziwi-state-view__btn').first();
    if (await tplB.isVisible().catch(() => false)) await tplB.click();
    await sleep(600);
    const itemsB = page.locator('.mex-item');
    const countB = await itemsB.count();
    for (let i = 0; i < countB; i += 1) await itemsB.nth(i).locator('.mex-verdict--normal').click();
    await sleep(300);
    await page.locator('.ziwi-actionbar__btn--primary').click(); // 提交并完工
    await sleep(3000);
    const extraB2 = await page.locator('.ziwi-receipt__extra').innerText().catch(() => '');
    const eqAfterB = await api('GET', `/equipment/${EQ_ID}`);
    const m6c = afterStartB.data?.status === 'maintenance' && eqAfterB.data?.status === 'running'
      && !/已生成安灯/.test(extraB2);
    await page.screenshot({ path: path.join(SHOT, 'M6_normal_path.png') });
    rec('M6c', '无异常路径：maintenance → running（不开安灯）', m6c ? 'PASS' : 'FAIL',
      `task=${taskBId} 项数=${countB} 开工后=${afterStartB.data?.status} 完工后=${eqAfterB.data?.status} 回执extra="${extraB2.replace(/\n/g, ' | ')}"`);
  } catch (e) {
    rec('M1-M6', '点检执行', 'FAIL', e.message.slice(0, 240));
    await page.screenshot({ path: path.join(SHOT, 'M_fail.png') }).catch(() => {});
  }

  /* ================================================================ *
   * 通用：三页 × 两视口 无横向溢出
   * ================================================================ */
  const pagesToCheck = [
    ['出库执行', `#/wms/issue-orders/${orderA}/execute`],
    ['点检执行', `#/equipment/maintenance-tasks/${TASK_ID}/execute`],
    ['设备任务', `#/equipment/tasks?code=${encodeURIComponent(EQ_CODE)}`],
  ];
  for (const [name, hash] of pagesToCheck) {
    const p = await ctx.newPage();
    for (const vp of [{ width: 412, height: 915 }, { width: 1024, height: 768 }]) {
      try {
        await p.setViewportSize(vp);
        await p.goto(`${BASE}/${hash}`, { waitUntil: 'networkidle', timeout: 30000 });
        await sleep(1500);
        const m = await p.evaluate(() => ({
          scrollW: document.documentElement.scrollWidth,
          innerW: window.innerWidth,
          ff: document.documentElement.getAttribute('data-form-factor'),
        }));
        const ok = m.scrollW <= m.innerW + 1;
        rec('G2', `${name} ${vp.width}×${vp.height} 无横向溢出`, ok ? 'PASS' : 'FAIL',
          `scrollWidth=${m.scrollW} innerWidth=${m.innerW} 形态=${m.ff}`);
        await p.screenshot({ path: path.join(SHOT, `G2_${name}_${vp.width}.png`) });
      } catch (e) {
        rec('G2', `${name} ${vp.width} 溢出检查`, 'FAIL', e.message.slice(0, 140));
      }
    }
    await p.close();
  }

  const out = {
    at: new Date().toISOString(), base: BASE,
    orderA: { no: ORDER_A, id: orderA }, orderB: { no: ORDER_B, id: orderB },
    eq: { code: EQ_CODE, id: EQ_ID, task: TASK_ID },
    results, consoleErrors: errs.slice(0, 12),
  };
  fs.writeFileSync(path.join(SHOT, 'result.json'), JSON.stringify(out, null, 2), 'utf8');
  console.log('\n=== SUMMARY ===');
  for (const r of results) console.log(`${r.status} ${r.id} ${r.name}`);
  console.log('consoleErrors =', errs.length);
  await browser.close();
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
