/** Controlled browser regression checks. Start Vite, then run with Playwright
 * available (PLAYWRIGHT_MODULE may point to a temporary install).
 * Uses installed Chrome and mocked API/vendor responses; no personal DB or LLM.
 */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const base = process.env.BOARD_TEST_URL || 'http://127.0.0.1:5173'
await mkdir('/tmp/resume-item7-browser', { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const errors = []
const DAY = 86400000
const jd = 'Build reliable APIs and test distributed software. '.repeat(20)
const source = (url) => ({ text: jd, source_url: url, apply_url: url + '/application', adapter: 'greenhouse', title: 'Software Engineer', warnings: [] })
const job = (id, age = DAY, company = 'acme') => ({ url: `https://job-boards.greenhouse.io/${company}/jobs/${id}`, company_slug: company, title: `Software Engineer ${id}`, location: 'Austin, TX', created_at: new Date(Date.now() - age).toISOString().replace('Z', '') })
const feed = (page, total = 3) => ({ jobs: Array.from({ length: 18 }, (_, i) => job(page * 100 + i)), total_pages: total, has_more: page < total })
const json = (route, data, status = 200) => route.fulfill({ status, json: data })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
async function setup(options = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 950 }, ...options })
  const page = await context.newPage()
  page.setDefaultTimeout(10000)
  page.on('pageerror', e => errors.push(e.message))
  await page.addInitScript(() => {
    localStorage.setItem('has-tailored', '1')
    document.addEventListener('DOMContentLoaded', () => {
      document.documentElement.dataset.resumeAgent = 'installed'
      window.dispatchEvent(new Event('resume-agent:present'))
    })
  })
  await page.route('**/*', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (url.hostname === 't1.gstatic.com') {
      const company = url.searchParams.get('url')
      if (company === 'https://broken.com') return route.abort()
      const size = company === 'https://tiny.com' ? 16 : 128
      return route.fulfill({ contentType: 'image/svg+xml', body: `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}"><rect width="100%" height="100%" fill="#ad6f25"/></svg>` })
    }
    if (url.origin !== base) return route.abort()
    if (req.resourceType() === 'document') return route.continue()
    if (url.pathname === '/resumes') return json(route, [{ id: 'resume1', filename: 'base.tex', label: 'Base résumé', is_default: true }])
    if (url.pathname === '/profile') return json(route, { id: 'default', name: 'Test Person' })
    if (url.pathname === '/jobs') return json(route, [])
    if (url.pathname === '/board') return json(route, feed(Number(url.searchParams.get('page') || 1)))
    if (url.pathname === '/board/resolve' || url.pathname === '/jd/from-url') return json(route, source(req.postDataJSON().url))
    return route.continue()
  })
  return { page, context }
}
async function check(name, fn, options) {
  const { page, context } = await setup(options)
  try { await fn(page); console.log(`PASS ${name}`) }
  finally { await context.close() }
}
try {
  await check('empty Board and network failure both recover through refresh/retry', async page => {
    let failed = false
    let empty = true
    await page.route('**/board?*', route => failed ? json(route, { detail: 'Temporary outage' }, 503)
      : json(route, empty ? { jobs: [], total_pages: 0, has_more: false } : feed(1)))
    await page.goto(base + '/board')
    await page.getByText('No recent roles on this page.').waitFor()
    assert.equal(await page.locator('[aria-label="Board pagination"]').count(), 0)
    empty = false
    await page.getByRole('button', { name: 'Refresh Board' }).click()
    await page.getByText('Software Engineer 100', { exact: true }).waitFor()
    failed = true
    await page.reload()
    await page.getByRole('button', { name: /^retry$/i }).waitFor()
    failed = false
    await page.getByRole('button', { name: /^retry$/i }).click()
    await page.getByText('Software Engineer 100', { exact: true }).waitFor()
  })
  await check('cached rows expire during an outage', async page => {
    let failed = false
    const rows = [job(1, 14 * DAY - 2000)]
    await page.clock.install()
    await page.route('**/board?*', route => failed ? json(route, { detail: 'Offline' }, 503)
      : json(route, { jobs: rows, total_pages: 1, has_more: false }))
    await page.goto(base + '/board')
    await page.getByText('Software Engineer 1', { exact: true }).waitFor()
    failed = true
    await page.clock.fastForward(61000)
    await page.getByText('Software Engineer 1', { exact: true }).waitFor({ state: 'hidden' })
    await page.getByText('No recent roles on this page.').waitFor()
  })
  await check('same-path URL changes reset the handoff without retaining the previous draft', async page => {
    let calls = 0
    await page.route('**/board/resolve', route => { calls++; return json(route, source(route.request().postDataJSON().url)) })
    await page.goto(base + '/?from=board&url=' + encodeURIComponent(job(1).url))
    await page.waitForFunction(text => document.querySelector('#jd')?.value === text, jd)
    await page.locator('#jd').fill('First posting draft')
    const next = '/?from=board&url=' + encodeURIComponent(job(2).url)
    await page.evaluate(nextUrl => { history.pushState(null, '', nextUrl); window.dispatchEvent(new PopStateEvent('popstate')) }, next)
    await page.waitForFunction(text => document.querySelector('#jd')?.value === text, jd)
    assert.equal(calls, 2)
    assert.equal(await page.locator('input[type="url"]').inputValue(), job(2).url)
  })
  await check('confirmed closure invalidates cached Board on return', async page => {
    let closed = false
    let boardCalls = 0
    await page.route('**/board?*', route => { boardCalls++; return json(route, { jobs: closed ? [] : [job(1)], total_pages: closed ? 0 : 1, has_more: false }) })
    await page.route('**/board/resolve', route => { closed = true; return json(route, { detail: 'This job is no longer available.' }, 410) })
    await page.goto(base + '/board')
    await page.getByRole('button', { name: 'Tailor & Apply' }).click()
    await page.getByRole('link', { name: 'Back to Board' }).click()
    await page.getByText('No recent roles on this page.').waitFor()
    assert(boardCalls >= 2)
    assert.equal(await page.getByText('Software Engineer 1', { exact: true }).count(), 0)
  })
  await check('pagination disables every control, scrolls main on success, clamps shrinking feed', async page => {
    const gate = deferred()
    let shrinking = false
    await page.route('**/board?*', async route => {
      const n = Number(new URL(route.request().url()).searchParams.get('page'))
      if (n === 2) await gate.promise
      return json(route, shrinking && n === 3 ? { jobs: [], total_pages: 1, has_more: false } : feed(n, shrinking ? 1 : 3))
    })
    await page.goto(base + '/board')
    await page.getByText('Software Engineer 100', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Page 2', exact: true }).click()
    for (const button of await page.locator('[aria-label="Board pagination"] button').all()) assert(await button.isDisabled())
    gate.resolve()
    await page.getByText('Software Engineer 200', { exact: true }).waitFor()
    await page.waitForFunction(() => Math.abs(document.querySelector('[aria-busy]').getBoundingClientRect().top - document.querySelector('main').getBoundingClientRect().top - 16) < 3)
    assert.equal(await page.evaluate(() => window.scrollY), 0)
    await page.getByRole('button', { name: 'Page 3', exact: true }).click()
    await page.getByText('Software Engineer 300', { exact: true }).waitFor()
    assert(await page.getByRole('button', { name: 'Next →' }).isDisabled())
    await page.getByRole('button', { name: 'Page 2', exact: true }).click()
    await page.getByText('Software Engineer 200', { exact: true }).waitFor()
    shrinking = true
    await page.getByRole('button', { name: 'Page 3', exact: true }).click()
    await page.getByText('Software Engineer 100', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: 'Page 1', exact: true }).getAttribute('aria-current'), 'page')
  })
  await check('logos retain good images and replace tiny/broken images; cached expiry', async page => {
    const rows = [job(1, DAY, 'good'), job(2, DAY, 'tiny'), job(3, DAY, 'broken'), job(4, 14 * DAY - 2000, 'expiring')]
    await page.route('**/board?*', route => json(route, { jobs: rows, total_pages: 1, has_more: false }))
    await page.goto(base + '/board')
    await page.getByText('Software Engineer 1', { exact: true }).waitFor()
    await page.waitForFunction(() => document.querySelectorAll('main img').length === 2)
    assert(await page.getByRole('img', { name: 'good logo' }).isVisible())
    assert.equal(await page.getByRole('img', { name: 'tiny logo' }).count(), 0)
    await page.getByText('Software Engineer 4', { exact: true }).waitFor({ state: 'hidden' })
  })
  await check('StrictMode handoff fetches once, fills JD, and passes apply URL into create', async page => {
    let calls = 0
    let submitted
    await page.route('**/board/resolve', route => { calls++; return json(route, source(route.request().postDataJSON().url)) })
    await page.route('**/jobs', route => {
      if (route.request().method() === 'POST') { submitted = route.request().postData(); return json(route, { job_id: 'test-run' }) }
      return json(route, [])
    })
    await page.route('**/jobs/test-run', route => json(route, { detail: 'Test run' }, 404))
    await page.goto(base + '/board')
    await page.getByRole('button', { name: 'Tailor & Apply' }).first().click()
    await page.waitForFunction(text => document.querySelector('#jd')?.value === text, jd)
    assert.equal(calls, 1)
    assert(new URL(page.url()).searchParams.get('from') === 'board')
    await page.getByRole('button', { name: /tailor my résumé/i }).click()
    await page.waitForURL('**/tailor/test-run')
    assert(submitted.includes(jd))
    assert(submitted.includes('/jobs/100/application'))
    assert(submitted.includes('resume1'))
  })
  await check('slow handoff and focus never overwrite a user draft', async page => {
    const gate = deferred()
    let calls = 0
    await page.route('**/board/resolve', async route => { calls++; await gate.promise; return json(route, source(route.request().postDataJSON().url)) })
    await page.goto(base + '/?from=board&url=' + encodeURIComponent(job(1).url))
    await page.locator('#jd').fill('My edited brief while the network is slow.')
    gate.resolve()
    await page.getByText('filled from', { exact: false }).waitFor()
    assert.equal(await page.locator('#jd').inputValue(), 'My edited brief while the network is slow.')
    await page.locator('#jd').fill('')
    await page.evaluate(() => { window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange')) })
    assert.equal(await page.locator('#jd').inputValue(), '')
    assert.equal(calls, 1)
  })
  for (const status of [404, 410, 502]) {
    await check(`${status} handoff stays on Compose with recovery`, async page => {
      let calls = 0
      await page.route('**/board/resolve', route => {
        calls++
        return calls === 1 ? json(route, { detail: status === 502 ? 'Please retry.' : 'This listing is no longer available.' }, status) : json(route, source(route.request().postDataJSON().url))
      })
      await page.goto(base + '/?from=board&url=' + encodeURIComponent(job(1).url))
      await page.getByRole('alert').waitFor()
      assert.equal(new URL(page.url()).pathname, '/')
      assert(await page.getByRole('link', { name: 'Back to Board' }).isVisible())
      assert.equal(await page.getByRole('button', { name: /^retry$/i }).count(), status === 502 ? 1 : 0)
      if (status === 502) {
        await page.locator('#jd').fill('Edited before retry')
        await page.getByRole('button', { name: /^retry$/i }).click()
        await page.getByText('filled from', { exact: false }).waitFor()
        assert.equal(await page.locator('#jd').inputValue(), 'Edited before retry')
        assert.equal(calls, 2)
      } else {
        await page.getByRole('link', { name: 'Back to Board' }).click()
        await page.getByText('Software Engineer 100', { exact: true }).waitFor()
      }
    })
  }
  await check('manual URL handoff remains supported', async page => {
    let boardCalls = 0
    await page.route('**/board/resolve', route => { boardCalls++; return json(route, {}, 500) })
    await page.goto(base + '/?url=' + encodeURIComponent(job(1).url))
    await page.waitForFunction(text => document.querySelector('#jd')?.value === text, jd)
    assert.equal(boardCalls, 0)
  })
  await check('pasted link shows freshness in local calendar days (T28)', async page => {
    // 17:30 on Sep 22 in Los Angeles is already Sep 23 in UTC: the Workday bare
    // date must still read "today", and every phrase must fit a phone line.
    await page.clock.setFixedTime(new Date('2026-09-23T00:30:00Z'))
    const cases = [
      [{ posted_at: '2026-09-22', updated_at: null, board: null }, 'posted Sep 22, 2026 (today)'],
      [{ posted_at: '2026-08-11T22:00:35', updated_at: '2026-08-26T23:07:27', board: 'added' },
        'posted Aug 11, 2026 (42 days ago) · updated Aug 26, 2026 · company added to Board'],
      [{ posted_at: '2026-09-22T23:03:03', updated_at: '2026-09-22T23:03:03', board: 'tracked' },
        'posted Sep 22, 2026 (today) · company already on Board'],
      [{ posted_at: null, updated_at: null, board: null }, 'posting date not provided by this site'],
    ]
    for (const [dates, expected] of cases) {
      await page.unroute('**/jd/from-url')
      await page.route('**/jd/from-url', route => json(route, { ...source(route.request().postDataJSON().url), ...dates }))
      await page.goto(base + '/?url=' + encodeURIComponent(job(1).url))
      const line = page.locator('p', { hasText: /^(posted|posting date)/ })
      await line.waitFor()
      assert.equal(await line.textContent(), expected)
      assert(await line.evaluate(p => [...p.children].every(s => s.getBoundingClientRect().right <= p.getBoundingClientRect().right + 0.5)),
        `freshness overflows at 375px: ${expected}`)
    }
  }, { viewport: { width: 375, height: 812 }, timezoneId: 'America/Los_Angeles' })
  await check('background refresh leaves reading position alone', async page => {
    let calls = 0
    await page.route('**/board?*', route => { calls++; return json(route, feed(1)) })
    await page.clock.install()
    await page.goto(base + '/board')
    await page.getByText('Software Engineer 100', { exact: true }).waitFor()
    await page.evaluate(() => { document.querySelector('main').scrollTop = 600 })
    await page.clock.fastForward(61000)
    await page.waitForFunction(() => document.querySelector('[aria-busy]')?.getAttribute('aria-busy') === 'false')
    assert(calls >= 2)
    assert.equal(await page.locator('main').evaluate(el => el.scrollTop), 600)
  })
  await check('one card per role names its count of openings', async page => {
    const jobs = [{ ...job(1), openings: 3 }, { ...job(2), openings: 1 }, job(3)]
    await page.route('**/board?*', route => json(route, { jobs, total_pages: 1, has_more: false }))
    await page.goto(base + '/board')
    await page.getByText('Software Engineer 3', { exact: true }).waitFor()
    const label = page.getByText(/openings$/)
    assert.deepEqual(await label.allTextContents(), ['•3 openings'])
    const line = label.locator('..')
    assert(await line.evaluate(p => [...p.children].every(s => s.getBoundingClientRect().right <= p.getBoundingClientRect().right + 0.5)),
      'openings overflow at 375px')
    await line.screenshot({ path: '/tmp/resume-item7-browser/openings.png' })
  }, { viewport: { width: 375, height: 812 } })
  await check('mobile and reduced motion keep Board controls readable', async page => {
    await page.route('**/board?*', route => json(route, feed(Number(new URL(route.request().url()).searchParams.get('page') || 1), 10)))
    await page.goto(base + '/board')
    await page.getByText('Software Engineer 100', { exact: true }).waitFor()
    const title = await page.getByText('Software Engineer 100', { exact: true }).boundingBox()
    assert(title.width >= 120, `job title is squeezed to ${title.width}px`)
    const next = page.getByRole('button', { name: 'Next →' })
    await next.scrollIntoViewIfNeeded()
    const box = await next.boundingBox()
    assert(box.x + box.width <= 390)
    await next.click()
    await page.getByText('Software Engineer 200', { exact: true }).waitFor()
    assert.equal(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth), true)
    await page.screenshot({ path: '/tmp/resume-item7-browser/mobile.png' })
  }, { viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' })
  assert.deepEqual(errors, [])
  console.log('All Board browser checks passed; no uncaught page errors.')
} finally { await browser.close() }
