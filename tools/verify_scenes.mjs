#!/usr/bin/env node
// 場景包 headless 冒煙測試：把 scratchpad 驗證流程固化進 repo。
//
// 用法：node tools/verify_scenes.mjs
//
// 行為：
//   1. 自動探索 scenes/*/scene.json，逐場景驗證（目前應有 test1、tainan_yongkang）
//   2. 自行 spawn `python3 -m http.server 8946`（cwd = repo 根，8946 避免撞埠），
//      無論成敗都在 finally 必殺
//   3. 每場景以 Playwright chromium headless 開
//      http://127.0.0.1:8946/player/index.html?scene=<code>，
//      等 networkidle + 2.5s 後斷言：
//        - 零 console error（含 pageerror 未捕捉例外）
//        - 零外部請求（非 127.0.0.1 且非 blob: 即算外部——three.js 是本地 vendor，
//          不應打任何 CDN）
//        - window.__colliders 恰 2 台且每台 pivot.position 無 NaN
//        - 頁面無「場景載入失敗」overlay（main.js showError 的唯一出口）
//   4. 輸出逐場景 JSON 結果；任一場景失敗 exit 1，全過 exit 0
//
// Playwright 解析 fallback（b、c 是**本機器特定**路徑，換機器請自行
// `npm i playwright` 或改路徑；本機已驗證可用）：
//   a. createRequire 直接 require('playwright')
//   b. a 失敗 → 從 npx 快取的 module path 載入：
//      ~/.npm/_npx/9833c18b2d85bc59/node_modules
//   c. launch 失敗 → 改用 executablePath：
//      ~/Library/Caches/ms-playwright/chromium_headless_shell-1223/
//        chrome-headless-shell-mac-arm64/chrome-headless-shell

import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import os from 'node:os';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 8946;
const BASE = `http://127.0.0.1:${PORT}`;
const SETTLE_MS = 8000;      // networkidle 後再等這麼久，讓 GLB 載入與首幀模擬跑完
// 2500 在機器忙時不夠：test1（trajectory 2.3MB + ground 3.5MB + car.glb 18.5MB）會在
// 載完前就被斷言，回報 colliderCount 0 但 console error 0——看起來像場景壞掉，其實是計時。
// 這個假失敗會讓人以為自己改壞了東西，成本遠高於多等幾秒。
const GOTO_TIMEOUT_MS = 30000;

// ── Playwright 解析（含機器特定 fallback，見檔頭）────────────────────────────
function loadPlaywright() {
  const req = createRequire(import.meta.url);
  try {
    return req('playwright');
  } catch {
    // fallback b：npx 快取（機器特定路徑）
    const npxModules = path.join(os.homedir(), '.npm/_npx/9833c18b2d85bc59/node_modules');
    const reqNpx = createRequire(path.join(npxModules, '_resolve_anchor.js'));
    return reqNpx('playwright');
  }
}

async function launchChromium(pw) {
  try {
    return await pw.chromium.launch({ headless: true });
  } catch (launchErr) {
    // fallback c：直接指 headless shell 執行檔（機器特定路徑）
    const shell = path.join(
      os.homedir(),
      'Library/Caches/ms-playwright/chromium_headless_shell-1223',
      'chrome-headless-shell-mac-arm64/chrome-headless-shell',
    );
    if (!existsSync(shell)) throw launchErr;
    return await pw.chromium.launch({ headless: true, executablePath: shell });
  }
}

// ── 場景探索：scenes/ 下有 scene.json 的目錄都算 ─────────────────────────────
function discoverScenes() {
  const scenesDir = path.join(REPO_ROOT, 'scenes');
  return readdirSync(scenesDir, { withFileTypes: true })
    .filter(d => d.isDirectory() && existsSync(path.join(scenesDir, d.name, 'scene.json')))
    .map(d => d.name)
    .sort();
}

// ── HTTP server 就緒等待 ─────────────────────────────────────────────────────
async function waitForServer(timeoutMs = 10000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const res = await fetch(`${BASE}/player/index.html`);
      if (res.ok) return;
    } catch {
      // server 還沒起來，繼續等
    }
    await new Promise(r => setTimeout(r, 200));
  }
  throw new Error(`http.server（port ${PORT}）在 ${timeoutMs}ms 內沒起來`);
}

// 非 127.0.0.1 且非 blob: 即算外部請求
function isExternal(url) {
  return !url.startsWith('http://127.0.0.1:') && !url.startsWith('blob:');
}

// ── 單一場景驗證 ─────────────────────────────────────────────────────────────
async function verifyScene(browser, code) {
  const errors = [];
  const consoleErrors = [];
  const externalRequests = [];
  const page = await browser.newPage();
  try {
    page.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', err => consoleErrors.push(`pageerror: ${err.message}`));
    page.on('request', req => {
      if (isExternal(req.url())) externalRequests.push(req.url());
    });

    await page.goto(`${BASE}/player/index.html?scene=${code}`,
                    { waitUntil: 'networkidle', timeout: GOTO_TIMEOUT_MS });
    await page.waitForTimeout(SETTLE_MS);

    const state = await page.evaluate(() => {
      const colliders = window.__colliders || [];
      const positions = colliders.map(c =>
        c.pivot ? [c.pivot.position.x, c.pivot.position.y, c.pivot.position.z] : null);
      const overlay = Array.from(document.querySelectorAll('div'))
        .some(d => (d.textContent || '').includes('場景載入失敗'));
      return { colliderCount: colliders.length, positions, overlay };
    });

    if (consoleErrors.length > 0) {
      errors.push(`console error ×${consoleErrors.length}：${consoleErrors.join(' | ')}`);
    }
    if (externalRequests.length > 0) {
      errors.push(`外部請求 ×${externalRequests.length}：${externalRequests.join(' | ')}`);
    }
    if (state.colliderCount !== 2) {
      errors.push(`__colliders 應恰 2 台，實得 ${state.colliderCount}`);
    }
    const pivotNaN = state.positions.some(p =>
      !p || p.some(v => typeof v !== 'number' || Number.isNaN(v)));
    if (pivotNaN) {
      errors.push(`pivot.position 有 NaN 或缺 pivot：${JSON.stringify(state.positions)}`);
    }
    if (state.overlay) {
      errors.push('頁面出現「場景載入失敗」overlay');
    }

    return {
      scene: code,
      ok: errors.length === 0,
      checks: {
        consoleErrors: consoleErrors.length,
        externalRequests: externalRequests.length,
        colliderCount: state.colliderCount,
        pivotNaN,
        errorOverlay: state.overlay,
      },
      errors,
    };
  } catch (e) {
    errors.push(`驗證流程異常：${e.message}`);
    return { scene: code, ok: false, checks: null, errors };
  } finally {
    await page.close().catch(() => {});
  }
}

// ── 主流程：server 與 browser 都掛在 try/finally 下，失敗路徑也必殺 ──────────
async function main() {
  const scenes = discoverScenes();
  if (scenes.length === 0) {
    console.error('scenes/ 下找不到任何 scene.json');
    process.exit(1);
  }

  let server = null;
  let browser = null;
  const results = [];
  try {
    server = spawn('python3', ['-m', 'http.server', String(PORT), '--bind', '127.0.0.1'],
                   { cwd: REPO_ROOT, stdio: 'ignore' });
    // 保險：就算 finally 沒跑到（process 被外力終結以外的情況），exit 時也補殺
    process.on('exit', () => { try { server.kill('SIGKILL'); } catch { /* 已死 */ } });
    await waitForServer();

    const pw = loadPlaywright();
    browser = await launchChromium(pw);

    for (const code of scenes) {
      results.push(await verifyScene(browser, code));
    }
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) server.kill('SIGTERM');
  }

  console.log(JSON.stringify(results, null, 2));
  const failed = results.filter(r => !r.ok);
  if (failed.length > 0) {
    console.error(`✗ ${failed.length}/${results.length} 場景失敗：${failed.map(r => r.scene).join(', ')}`);
    process.exit(1);
  }
  console.log(`✓ ${results.length} 場景全過`);
  process.exit(0);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
