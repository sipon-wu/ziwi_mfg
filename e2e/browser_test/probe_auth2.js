// probe_auth2.js - 确认 BUG-5：work-order release 是否仍 500（先列表拿到刚建的 WO id）
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const API = 'https://mfg1.ziwi.cn/api/v1';
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const log = (...a) => console.log(...a);

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('https://mfg1.ziwi.cn/#/login', { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(800);
  await page.fill('#van-field-1-input', 'test_admin');
  await page.fill('#van-field-2-input', 'test123456');
  await page.click('button[type="submit"]');
  await sleep(2500);
  const token = await page.evaluate(() => localStorage.getItem('access_token'));
  log('token:', token ? 'ok' : 'MISSING');

  const api = async (method, p, body) => page.evaluate(async ({ method, url, body, token }) => {
    const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token }, body: body ? JSON.stringify(body) : undefined });
    let data; try { data = await res.json(); } catch { data = ''; }
    return { status: res.status, body: data };
  }, { method, url: API + p, body, token });

  const list = await api('GET', '/work-orders?keyword=E2E_BROWSER_&page_size=50');
  log('GET /work-orders?keyword=E2E_BROWSER_ →', list.status, JSON.stringify(list.body).slice(0, 400));
  // 解析 id
  let woId = null;
  const d = list.body && list.body.data;
  if (d) {
    const items = Array.isArray(d) ? d : (d.items || []);
    if (items.length) woId = items[0].id;
  }
  log('找到 WO id =', woId);
  if (woId) {
    const rel = await api('POST', `/work-orders/${woId}/release`, { force_release: true, force_reason: 'E2E探针' });
    log('★ POST /work-orders/' + woId + '/release →', rel.status, JSON.stringify(rel.body).slice(0, 300));
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
