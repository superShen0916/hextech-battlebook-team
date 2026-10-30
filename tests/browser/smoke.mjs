// Maintained end-to-end checks shared by both assistants. No saved Chrome profile.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(project, 'tools/browser/package.json'));
let chromium;
try {
  ({chromium} = require('playwright-core'));
  const expected = require('./package.json').devDependencies['playwright-core'];
  assert.equal(require('playwright-core/package.json').version, expected, 'browser dependency version mismatch');
} catch (error) {
  throw new Error('Browser dependency missing/wrong. In tools/browser run pinned Node npm ci --ignore-scripts. ' + error.message);
}
const argv = process.argv.slice(2);
const arg = name => argv.includes(name) ? argv[argv.indexOf(name) + 1] : null;
const doctor = argv.includes('--doctor');
const root = arg('--root') ? path.resolve(arg('--root')) : null;
const remote = arg('--url');
const out = path.resolve(arg('--out') || path.join(project, 'outputs/workflow-browser'));
const results = {ok: false, checks: [], views: [], errors: [], failedResponses: []};
let browser, server, page, context;
const deadline = setTimeout(() => {console.error('BROWSER_TIMEOUT'); process.exitCode = 1; void cleanup();}, 210000);
deadline.unref();

async function cleanup() {
  await browser?.close().catch(() => {});
  if (server) await new Promise(resolve => server.close(resolve));
}
async function launch() {
  const executable = process.env.BATTLEBOOK_BROWSER_EXECUTABLE;
  if (executable) {
    assert.ok(path.isAbsolute(executable) && fs.existsSync(executable), 'BATTLEBOOK_BROWSER_EXECUTABLE must be an existing absolute path');
    return chromium.launch({executablePath: executable, headless: true, timeout: 20000});
  }
  let last;
  for (const channel of ['chrome', 'msedge']) {
    try { return await chromium.launch({channel, headless: true, timeout: 20000}); }
    catch (error) { last = error; }
  }
  throw new Error('Install Chrome/Edge or set BATTLEBOOK_BROWSER_EXECUTABLE. ' + last.message);
}
function staticServer(base) {
  const types = {'.js':'text/javascript', '.css':'text/css', '.html':'text/html; charset=utf-8',
    '.json':'application/json', '.png':'image/png', '.svg':'image/svg+xml', '.webp':'image/webp', '.jpg':'image/jpeg'};
  return http.createServer((request, response) => {
    if (!['GET', 'HEAD'].includes(request.method)) {response.writeHead(405).end(); return;}
    try {
      const url = new URL(request.url, 'http://localhost');
      const rel = decodeURIComponent(url.pathname);
      const file = path.resolve(base, '.' + (rel.endsWith('/') ? rel + 'index.html' : rel));
      if (!file.startsWith(base + path.sep)) {response.writeHead(403).end(); return;}
      if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {response.writeHead(404).end(); return;}
      response.writeHead(200, {'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'Cache-Control':'no-store'});
      if (request.method === 'HEAD') response.end(); else fs.createReadStream(file).pipe(response);
    } catch {response.writeHead(400).end();}
  });
}
const check = value => {results.checks.push(value); console.log('PASS', value);};
const number = value => Number(value.replaceAll(',', '').replaceAll('+', ''));
const beijingStamp=ms=>{const d=new Date(ms+8*3600*1000),p2=n=>String(n).padStart(2,'0');
  return `${d.getUTCFullYear()}/${p2(d.getUTCMonth()+1)}/${p2(d.getUTCDate())} ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;};


try {
  browser = await launch();
  if (doctor) {
    console.log('BROWSER_ENVIRONMENT_OK playwright-core=' + require('playwright-core/package.json').version);
  } else {
    assert.ok(Boolean(root) !== Boolean(remote), 'Provide exactly one of --root and --url');
    fs.mkdirSync(out, {recursive: true});
    let base;
    if (root) {
      assert.ok(fs.existsSync(path.join(root, 'index.html')), 'Build first: Workflow.cmd prepare');
      server = staticServer(root);
      await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
      base = new URL('http://127.0.0.1:' + server.address().port + '/');
    } else {
      base = new URL(remote);
      assert.equal(base.origin, 'https://hextech-battlebook.app.workbuddy.host');
      assert.equal(base.searchParams.get('sharecode'), '7ZFAIH5YHV');
    }
    function url(relative = '/', query = {}) {
      const result = new URL(relative, base);
      if (base.searchParams.has('sharecode')) result.searchParams.set('sharecode', base.searchParams.get('sharecode'));
      for (const [key, value] of Object.entries(query)) result.searchParams.set(key, value);
      return result.href;
    }
    context = await browser.newContext({viewport: {width:1440, height:1000}, reducedMotion:'reduce'});
    // Abort every external origin: automated checks cannot write production visits,
    // play music or depend on external analytics. Same-origin assets stay real.
    await context.route('**/*', async route => {
      const request = new URL(route.request().url());
      if (request.origin !== base.origin) return route.abort();
      if (base.searchParams.has('sharecode')) request.searchParams.set('sharecode', base.searchParams.get('sharecode'));
      return route.continue({url:request.href});
    });
    page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on('pageerror', error => results.errors.push(error.message));
    page.on('response', response => {
      const u = new URL(response.url());
      if (u.origin === base.origin && response.status() >= 400 && /\.(json|js|css)$/.test(u.pathname))
        results.failedResponses.push({path:u.pathname, status:response.status()});
    });
    async function json(relative) {
      const response = await context.request.get(url(relative));
      assert.ok(response.ok(), relative + ': ' + response.status());
      return response.json();
    }
    async function fits(label, width) {
      const geometry = await page.evaluate(() => ({width:innerWidth, scroll:document.documentElement.scrollWidth}));
      assert.ok(geometry.scroll <= width + 1, label + ': ' + JSON.stringify(geometry));
      results.views.push({label, ...geometry});
    }
    async function count(locator, expected) {
      await locator.first().waitFor();
      assert.equal(await locator.count(), expected);
    }
    const snapshot = await json('/api/snapshot.json');
    const weekly = await json('/api/weekly.json');
    const profile = [...snapshot.players].sort((a,b) => (b.summary?.games || 0) - (a.summary?.games || 0))[0];
    const full = await json(profile.detail_url);
    const uniqueRecent = new Set(snapshot.players.filter(p => p.history_scope !== 'shared').flatMap(p => (p.recent || []).map(m => m.id)));
    // Product contract: lobby shows up to 10 distinct recent matches.
    const recentCount = Math.min(10, uniqueRecent.size);
    for (const width of [1440,390,320]) {
      await page.setViewportSize({width,height:1000});
      await page.goto(url(), {waitUntil:'domcontentloaded'});
      await page.locator('.weekly-hall').waitFor();
      await count(page.locator('#lobby-recent .lobby-game'), recentCount);
      assert.equal(await page.locator('#lobby-recent .text-button').count(), recentCount);
      for (const label of ['本周涨分榜','海斗总分榜']) {
        await page.getByRole('button', {name:label, exact:true}).click();
        assert.equal(await page.locator('.weekly-star').count() + await page.locator('.weekly-row').count(), weekly.reports[0].players.length);
        await fits(label, width);
      }
      await page.screenshot({path:path.join(out, `lobby-${width}.png`)});
      await page.getByRole('button', {name:'海斗分规则与计算公式',exact:true}).click();
      await page.locator('.rating-rules-dialog').waitFor();
      assert.match(await page.locator('.rating-rules-dialog').innerText(), /伤害占团队 40% 达到伤害单项100分/);
      assert.match(await page.locator('.rating-rules-dialog').innerText(), /击杀占团队 50% 达到击杀单项100分/);
      assert.equal(await page.locator('.equation-card').count(), 5); // 4.4 起多一张「战斗之夜」权重卡
      const dims = await page.locator('.rating-rules-dialog').evaluate(el => ({client:el.clientWidth,scroll:el.scrollWidth}));
      assert.ok(dims.scroll <= dims.client+1, JSON.stringify(dims));
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('.rating-rules-dialog').count(), 0);
      await page.locator('#lobby-recent .text-button').first().click();
      await count(page.locator('.roster-person'), 10);
      await fits('ten-player-report', width);
      await page.getByRole('button',{name:'关闭单局战报',exact:true}).click();
      await page.goto(url('/', {player:profile.id}), {waitUntil:'domcontentloaded'});
      const trigger = page.locator('.profile-coverage .rating-rule-trigger');
      await trigger.waitFor();
      for (const id of ['overview','preferences','heroes','hextech','honors','companions','matches'])
        assert.equal(await page.locator('#'+id).count(), 1, 'Missing section: '+id);
      const body = await page.locator('.profile-coverage').innerText();
      assert.ok(body.includes(Number(full.coverage.saved).toLocaleString('zh-CN')), 'Full saved history count missing');
      await trigger.click();
      await page.locator('.score-proof-grid strong').first().waitFor();
      assert.deepEqual((await page.locator('.score-proof-grid strong').allTextContents()).map(number),
        [profile.rating.base,profile.rating.settled_delta,profile.rating.week.delta,profile.rating.score]);
      await page.screenshot({path:path.join(out, `profile-rules-${width}.png`)});
      await page.keyboard.press('Escape');
      await fits('profile',width);
      // 每局海斗分：页面加减分必须与数据一致，且同周各局之和等于该周周分
      const matchRows = page.locator('.match-card-table tbody tr');
      const shownRows = Math.min(await matchRows.count(), 10);
      let deltaRows = 0;
      for (let i = 0; i < shownRows; i++) {
        const expected = full.recent[i]?.rating_delta;
        const cell = matchRows.nth(i).locator('.match-delta');
        const cellCount = await cell.count();
        if (typeof expected === 'number') {
          assert.equal(cellCount, 1, 'missing per-match delta at row ' + i);
          const text = (await cell.innerText()).trim();
          const parsed = Number((text.match(/^[+-]?\d+(?:\.\d+)?/) || [NaN])[0]);
          assert.ok(Math.abs(parsed - expected) < 0.051, `delta mismatch at row ${i}: ${text} / ${expected}`);
          if (full.recent[i]?.rating_mult > 1)
            assert.equal(await cell.locator('.night-flag').filter({hasText:'战斗之夜'}).count(), 1, 'missing battle-night flag at row ' + i);
          const volume = full.recent[i]?.rating_volume_mult;
          if (typeof volume==='number' && volume<1) {
            const badge = cell.locator('.volume-flag');
            assert.equal(await badge.count(),1,'missing per-week volume flag');
            assert.ok((await badge.innerText()).includes('第'+full.recent[i].rating_week_index+'局'));
          } else assert.equal(await cell.locator('.volume-flag').count(),0);
          deltaRows++;
        } else assert.equal(cellCount, 0, 'unexpected per-match delta at row ' + i);
      }
      const hasDeltas = full.recent.some(m => typeof m.rating_delta === 'number');
      assert.ok(deltaRows > 0 || !hasDeltas, 'no per-match haido delta rendered');
      const deltaSum = full.recent.filter(m => typeof m.rating_delta === 'number').reduce((sum, m) => sum + m.rating_delta, 0);
      const ledgerSum = (full.rating.settled_weeks || []).reduce((sum, w) => sum + w.delta, 0) + full.rating.week.delta;
      assert.ok(Math.abs(deltaSum - ledgerSum) < 0.2, `per-match sum ${deltaSum} != ledger ${ledgerSum}`);
      check(`${width}: per-match haido deltas ${deltaRows} rows, sum ${deltaSum.toFixed(1)}`);
      const radar = page.locator('.player-radar');
      await radar.scrollIntoViewIfNeeded();
      assert.equal(await radar.locator('[data-radar-axis]').count(),6);
      for (const [key,sample] of [['dpm','dpm'],['taken','taken'],['heal','heal'],['kill_participation','kill_participation'],['kda','kda'],['win_rate','wins']]) {
        const row = radar.locator(`[data-radar-axis="${key}"]`);
        const raw = full.summary[key];
        const expected = ['kill_participation','win_rate'].includes(key) ?
          (raw*100).toLocaleString('zh-CN',{maximumFractionDigits:1})+'%' :
          raw.toLocaleString('zh-CN',{maximumFractionDigits:key==='kda'?2:0});
        assert.equal(await row.locator('strong').innerText(),expected);
        assert.ok((await row.innerText()).includes(full.summary.samples[sample].toLocaleString('zh-CN')+' 场样本'));
      }
      assert.equal(await radar.locator('.radar-shape').count(),1);
      assert.ok(!(await radar.locator('.radar-shape').getAttribute('points')).includes('NaN'));
      await radar.getByText('怎么看这张图？',{exact:true}).click();
      await fits('radar',width);
      await radar.screenshot({path:path.join(out,`player-radar-${width}.png`)});
      const compareSelect = radar.getByRole('combobox',{name:'选择雷达图对比玩家',exact:true});
      assert.equal(await compareSelect.locator(`option[value="${profile.id}"]`).count(),0,'self comparison must be excluded');
      const comparison = snapshot.players.find(p=>p.id!==profile.id && (p.history_scope==='shared')===(profile.history_scope==='shared') &&
        ['dpm','taken','heal','kill_participation','kda','win_rate'].every(key=>typeof p.summary?.[key]==='number') &&
        ['dpm','taken','heal','kill_participation','kda','wins'].every(key=>(p.summary?.samples?.[key]||0)>=5));
      if (comparison) {
        await compareSelect.selectOption(comparison.id);
        assert.equal(await radar.locator('.radar-shape').count(),2);
        assert.equal(await radar.locator('.radar-shape-compare').count(),1);
        for (const key of ['dpm','taken','heal','kill_participation','kda','win_rate']) {
          const raw = comparison.summary[key];
          const expected = ['kill_participation','win_rate'].includes(key) ?
            (raw*100).toLocaleString('zh-CN',{maximumFractionDigits:1})+'%' :
            raw.toLocaleString('zh-CN',{maximumFractionDigits:key==='kda'?2:0});
          const cell = radar.locator(`[data-radar-axis="${key}"] [data-radar-player="${comparison.id}"]`);
          assert.equal(await cell.locator('strong').innerText(),expected);
          const sample = key==='win_rate'?'wins':key;
          assert.ok((await cell.innerText()).includes(comparison.summary.samples[sample].toLocaleString('zh-CN')+' 场样本'));
        }
        await fits('radar-comparison',width);
        await radar.screenshot({path:path.join(out,`radar-comparison-${width}.png`)});
        await radar.getByRole('button',{name:'取消对比',exact:true}).click();
        assert.equal(await compareSelect.inputValue(),'');
        assert.equal(await radar.locator('.radar-shape').count(),1);
        assert.equal(await radar.locator('.radar-other-value').count(),0);
      }
      check(`${width}: both boards, ${recentCount} recent links, 10-player report, full profile, rating proof, layout`);
    }
    // Check a real bonus-bearing match: the badge reports an included bonus, not an extra award twice.
    const pentaProfile = snapshot.players.find(p => (p.recent || []).some(m => m.rating_penta_bonus > 0));
    if (pentaProfile) {
      const pentaFull = await json(pentaProfile.detail_url);
      const index = pentaFull.recent.findIndex(m => m.rating_penta_bonus > 0);
      assert.ok(index >= 0);
      for (const width of [1440,390,320]) {
        await page.setViewportSize({width,height:1000});
        // 档案页会先渲染默认玩家的列表、再换成链接里的玩家；等这张表真的换成本玩家最新一场再翻页，
        // 否则按明细下标翻页会翻在过渡数据上（2026-10-31 采集后实测偶发）。
        const newest = beijingStamp(pentaFull.recent[0].started_ms);
        await page.goto(url('/', {player:pentaProfile.id}), {waitUntil:'domcontentloaded'});
        await page.locator('.match-card-table tbody tr').filter({hasText:newest}).first().waitFor({timeout:20000});
        // 每页条数随视口变化（桌面 20、窄屏 10），按实际渲染行数翻页，不能写死 10。
        const perPage = await page.locator('.match-card-table tbody tr').count();
        assert.ok(perPage > 0);
        for (let step = 0; step < Math.floor(index/perPage); step++)
          await page.getByRole('button',{name:'下一页',exact:true}).click();
        const row = page.locator('.match-card-table tbody tr').nth(index%perPage);
        const badge = row.locator('.penta-flag');
        await badge.waitFor();
        assert.equal(number((await badge.innerText()).replace('五杀奖励','')),pentaFull.recent[index].rating_penta_bonus);
        const dateCell = row.locator('td').first().locator(':scope > .cell-sub').first();
        assert.ok((await dateCell.boundingBox()).height <= 44, 'match date squeezed into vertical text');
        await row.scrollIntoViewIfNeeded();
        await fits('penta-bonus',width);
        await page.screenshot({path:path.join(out,`penta-bonus-${width}.png`)});
        await page.locator('.profile-coverage .rating-rule-trigger').click();
        await page.locator('.rules-component-proof').scrollIntoViewIfNeeded();
        const dims = await page.locator('.rating-rules-dialog').evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth}));
        assert.ok(dims.scroll<=dims.client+1,JSON.stringify(dims));
        await page.screenshot({path:path.join(out,`penta-rules-${width}.png`)});
        await page.keyboard.press('Escape');
      }
      check('real penta bonus badges and score components at 1440/390/320');
    }
    await page.setViewportSize({width:320,height:1000});
    // Choose an actual archived night and actual teammates, rather than fixed IDs/dates.
    const recap = await json('/api/recaps/index.json');
    assert.ok(recap.nights.length, 'No representative night for recap test');
    const night = recap.nights[0];
    await page.goto(url('/', {recap:'night',recap_player:night.players[0],recap_date:night.date,recap_fridays:'0'})+'#recaps', {waitUntil:'domcontentloaded'});
    await page.locator('.recap-score').waitFor();
    const nightData = await json('/api/recaps/nights/'+night.date+'.json');
    const nightGames = nightData.games.filter(g => g.members.some(m => m.profile_id === night.players[0]));
    assert.equal(number(await page.locator('.recap-score strong').first().innerText().then(x=>x.replace('场',''))), nightGames.length);
    await page.getByRole('button',{name:'分享这份回顾 ↗',exact:true}).click();
    const image = page.locator('.recap-share-dialog img');
    await image.waitFor();
    assert.ok(await image.evaluate(el=>el.complete && el.naturalWidth===1080));
    const share = new URL(await page.getByRole('textbox',{name:'回顾分享链接'}).inputValue());
    assert.equal(share.searchParams.get('recap_date'), night.date);
    if (remote) assert.equal(share.searchParams.get('sharecode'),'7ZFAIH5YHV');
    await page.screenshot({path:path.join(out,'recap-share-320.png')});
    await page.keyboard.press('Escape');
    const team = nightGames.find(g=>g.members.length>=2).members.slice(0,2).map(m=>m.profile_id);
    await page.goto(url('/',{recap:'team',recap_players:team.join(','),recap_period:'all'})+'#recaps',{waitUntil:'domcontentloaded'});
    await page.locator('.recap-score').waitFor();
    assert.equal(await page.locator('.recap-players [aria-pressed="true"]').count(),2);
    const teamData = await json('/api/recaps/players/'+team[0]+'.json');
    const common = teamData.games.filter(g=>team.every(id=>g.members.some(m=>m.profile_id===id)));
    assert.equal(number((await page.locator('.recap-score strong').first().innerText()).replace('场','')),common.length);
    await fits('recap-team',320);
    check('real night summary, PNG generation, restorable share link, real two-player intersection');
    await page.goto(url('/intel.html'),{waitUntil:'domcontentloaded'});
    await page.locator('h1').waitFor();
    await fits('intel',320);
    assert.deepEqual(results.errors, []);
    assert.deepEqual(results.failedResponses, []);
    results.ok = true;
  }
} catch (error) {
  results.error = error.stack;
  if (!doctor) {
    fs.mkdirSync(out, {recursive:true});
    await page?.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});
  }
  console.error(error.stack);
  process.exitCode = 1;
} finally {
  clearTimeout(deadline);
  await cleanup();
  if (!doctor) fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(results,null,2));
}
