import test from 'node:test'
import assert from 'node:assert/strict'
import {
    parseAndValidateUrlLines,
    filterRemainingInputAfterSubmit,
    aggregateRecentErrors,
    computeDirtySections,
    getStatusColor,
    buildTimelineBuckets,
    filterDownloadsByPeriod,
    buildLogAttemptBlocks,
    scrubPiiFromLogText,
    buildGitHubIssueDraft,
    buildGitHubIssueUrl,
    diagnoseErrorSignature,
    computeIniLineDiff,
    extractIniSections,
    extractSystemVersionsFromLogs,
    ensureExternalUrl,
    normalizeStoryUrl,
} from './dashboardLogic.ts'
import { STATUS_COLORS } from '../statusColors.ts'

test('parseAndValidateUrlLines parses full and scheme-less URLs and detects disabled or duplicate sites', () => {
    const input = [
        'https://archiveofourown.org/works/54918203',
        'royalroad.com/fiction/82194/chronicles-of-ember',
        'https://www.wattpad.com/story/99999',
        'not_a_url',
    ].join('\n')

    const previews = parseAndValidateUrlLines(
        input,
        ['wattpad'],
        new Set(['https://archiveofourown.org/works/54918203'])
    )

    assert.equal(previews.length, 4)
    assert.equal(previews[0].site, 'archiveofourown')
    assert.equal(previews[0].inferredTitle, 'Work #54918203')
    assert.equal(previews[0].isValid, true)
    assert.equal(previews[0].isDuplicateInFlight, true)

    assert.equal(previews[1].site, 'royalroad')
    assert.equal(previews[1].inferredTitle, 'Chronicles of ember')
    assert.equal(previews[1].isValid, true)
    assert.equal(previews[1].isDisabledSite, false)

    assert.equal(previews[2].site, 'wattpad')
    assert.equal(previews[2].isDisabledSite, true)

    assert.equal(previews[3].isValid, false)
})

test('filterRemainingInputAfterSubmit preserves rejected URLs instead of clearing all input', () => {
    const raw = [
        'https://archiveofourown.org/works/111',
        'invalid-url',
        'https://www.wattpad.com/story/222',
    ]
    const results = [
        { accepted: true, message: 'Accepted' },
        { accepted: false, message: 'Rejected invalid URL' },
        { accepted: false, message: 'Site disabled' },
    ]
    const remaining = filterRemainingInputAfterSubmit(raw, results)
    assert.equal(remaining, 'invalid-url\nhttps://www.wattpad.com/story/222')
})

test('aggregateRecentErrors deduplicates by URL while accumulating failure occurrences', () => {
    const now = Date.now()
    const waiting = [
        {
            url: 'https://www.fanfiction.net/s/13904512/1/',
            site: 'fanfiction',
            title: 'Echoes of Eternity',
            attempt_number: 2,
            error_message: 'HTTP 503 Cloudflare challenge',
            updated_at: new Date(now - 60_000).toISOString(),
        },
    ]
    const recent = [
        {
            url: 'https://www.fanfiction.net/s/13904512/1/',
            site: 'fanfiction',
            title: 'Echoes of Eternity',
            status: 'failed',
            error_message: 'HTTP 503 Cloudflare challenge',
            completed_at: new Date(now - 120_000).toISOString(),
        },
        {
            url: 'https://www.wattpad.com/story/28901234',
            site: 'wattpad',
            title: 'The Clockwork Sentinel',
            status: 'abandoned',
            error_message: 'HTTP 404 Not Found',
            completed_at: new Date(now - 300_000).toISOString(),
        },
    ]

    const errors = aggregateRecentErrors(waiting, recent, now)
    assert.equal(errors.length, 2)
    assert.equal(errors[0].url, 'https://www.fanfiction.net/s/13904512/1/')
    assert.equal(errors[0].occurrences, 3)
    assert.equal(errors[1].occurrences, 1)
})

test('buildLogAttemptBlocks de-interleaves concurrent site worker logs into self-contained attempt blocks', () => {
    const interleavedLogs = [
        { timestamp: '2026-10-27 17:15:12', level: 'info', message: '(archiveofourown) Processing https://archiveofourown.org/works/45892012', thread_site: 'archiveofourown' },
        { timestamp: '2026-10-27 17:15:13', level: 'info', message: '(fanfiction) Processing https://www.fanfiction.net/s/13904512/1/', thread_site: 'fanfiction' },
        { timestamp: '2026-10-27 17:15:15', level: 'debug', message: '(archiveofourown) FanFicFare CLI: fetching metadata & chapter list', thread_site: 'archiveofourown' },
        { timestamp: '2026-10-27 17:15:16', level: 'error', message: '(fanfiction) Failed https://www.fanfiction.net/s/13904512/1/: HTTP 503 Cloudflare challenge', thread_site: 'fanfiction' },
        { timestamp: '2026-10-27 17:15:17', level: 'warning', message: 'FFWaiter: Queued retry #2 for https://www.fanfiction.net/s/13904512/1/ (backoff: 2.0m)', thread_site: 'fanfiction' },
        { timestamp: '2026-10-27 17:15:20', level: 'info', message: "(archiveofourown) Apprise notification dispatched for 'The Stars Are Cold and Bright'", thread_site: 'archiveofourown' },
    ]

    const blocks = buildLogAttemptBlocks(
        interleavedLogs,
        [
            {
                url: 'https://www.fanfiction.net/s/13904512/1/',
                title: 'Echoes of Eternity: Chapter 42',
                site: 'fanfiction',
                status: 'failed',
                error_message: 'HTTP 503: Cloudflare anti-bot challenge\nTraceback: line 142',
            },
        ],
        [],
        [{ url: 'https://www.fanfiction.net/s/13904512/1/', stage: 'waiting_retry' }]
    )

    assert.equal(blocks.length, 2)
    assert.equal(blocks[0].site, 'fanfiction')
    assert.equal(blocks[0].isActive, true)
    assert.equal(blocks[0].activeStage, 'waiting_retry')
    assert.equal(blocks[1].site, 'archiveofourown')
    assert.equal(blocks[1].isActive, false)

    const ao3Block = blocks.find((b) => b.site === 'archiveofourown')!
    const ffnBlock = blocks.find((b) => b.site === 'fanfiction')!

    assert.ok(ao3Block)
    assert.equal(ao3Block.status, 'success')
    assert.equal(ao3Block.lines.length, 3)
    assert.equal(ao3Block.title, 'The Stars Are Cold and Bright')

    assert.ok(ffnBlock)
    assert.equal(ffnBlock.status, 'failed')
    assert.equal(ffnBlock.lines.length, 3)
    assert.equal(ffnBlock.title, 'Echoes of Eternity: Chapter 42')
    assert.ok(ffnBlock.traceback?.includes('Traceback: line 142'))
})

test('buildLogAttemptBlocks groups startup messages with non-story URLs into single lifecycle block', () => {
    const startupLogs = [
        { timestamp: '2026-10-28 11:07:11', level: 'info', message: 'Starting AutomatedFanfic v6.15.0' },
        { timestamp: '2026-10-28 11:07:12', level: 'info', message: 'For issues and updates, please go to https://github.com/MrTyton/AutomatedFanfic' },
        { timestamp: '2026-10-28 11:07:12', level: 'info', message: 'Using configuration file: /config/config.toml' },
        { timestamp: '2026-10-28 11:07:12', level: 'info', message: 'Python version: 3.15.2 (CPython)' },
        { timestamp: '2026-10-28 11:07:12', level: 'info', message: 'OS / Platform: Linux-6.1.106-Unraid-x86_64-with-glibc2.41 [Docker container]' },
        { timestamp: '2026-10-28 11:07:13', level: 'info', message: 'Calibre version: 9.17.0' },
        { timestamp: '2026-10-28 11:07:13', level: 'info', message: 'FanFicFare version: 4.62.18' },
        { timestamp: '2026-10-28 11:07:13', level: 'info', message: 'Apprise version: 2.0.1' },
        { timestamp: '2026-10-28 11:07:13', level: 'info', message: '--- Configuration Details ---' },
        { timestamp: '2026-10-28 11:07:13', level: 'info', message: 'Email Server: imap.gmail.com' },
        { timestamp: '2026-10-28 11:07:13', level: 'info', message: 'Calibre Path: http://192.168.1.161:8195/#Fanfiction' },
        { timestamp: '2026-10-28 11:07:13', level: 'info', message: 'Generating URL parsers from FanFicFare adapters...' },
        { timestamp: '2026-10-28 11:07:13', level: 'info', message: 'Generated 111 URL parsers for site recognition' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'Spawning 1 Worker Pool Process with 15 threads to match max_workers=20' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'Configuration loaded successfully from /config/config.toml' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'Apprise enabled with 1 notification target(s).' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'WebServer: Starting on 0.0.0.0:8080' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'Web dashboard enabled on 0.0.0.0:8080' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'HistoryWriter: started' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'Starting all processes...' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'Supervisor: Starting helper services...' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'Worker worker_0 started' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'All processes started successfully' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'Processes running. Press Ctrl+C to stop gracefully.' },
        { timestamp: '2026-10-28 11:07:14', level: 'info', message: 'WebServer: History database connection established' },
    ]

    const blocks = buildLogAttemptBlocks(startupLogs)
    const storyBlocks = blocks.filter((b) => b.kind === 'story_attempt')
    assert.equal(storyBlocks.length, 0)

    const systemBlocks = blocks.filter((b) => b.kind === 'system')
    assert.equal(systemBlocks.length, 1)
    assert.equal(systemBlocks[0].title, 'Application Startup & Lifecycle')
    assert.equal(systemBlocks[0].lines.length, 25)
    assert.equal(systemBlocks[0].isActive, false)
})

test('ensureExternalUrl and normalizeStoryUrl convert scheme-less URLs into absolute HTTPS URLs', () => {
    assert.equal(
        ensureExternalUrl('forums.sufficientvelocity.com/threads/scientia-weaponizes-the-future.82203'),
        'https://forums.sufficientvelocity.com/threads/scientia-weaponizes-the-future.82203'
    )
    assert.equal(
        ensureExternalUrl('https://archiveofourown.org/works/123'),
        'https://archiveofourown.org/works/123'
    )
    assert.equal(
        ensureExternalUrl('http://192.168.1.161:8195/#Fanfiction'),
        'http://192.168.1.161:8195/#Fanfiction'
    )
    assert.equal(ensureExternalUrl(''), '#')
    assert.equal(ensureExternalUrl(undefined), '#')

    const storyAttemptLogs = [
        {
            timestamp: '2026-10-28 05:59:43',
            level: 'info',
            message: '(sufficientvelocity) Processing forums.sufficientvelocity.com/threads/scientia-weaponizes-the-future.82203',
            story_url: 'forums.sufficientvelocity.com/threads/scientia-weaponizes-the-future.82203',
            thread_site: 'sufficientvelocity',
        },
    ]

    const blocks = buildLogAttemptBlocks(storyAttemptLogs)
    assert.equal(blocks.length, 1)
    assert.equal(blocks[0].kind, 'story_attempt')
    assert.equal(
        blocks[0].url,
        'https://forums.sufficientvelocity.com/threads/scientia-weaponizes-the-future.82203'
    )
    assert.equal(
        ensureExternalUrl(blocks[0].url),
        'https://forums.sufficientvelocity.com/threads/scientia-weaponizes-the-future.82203'
    )
})

test('buildLogAttemptBlocks groups worker attempt lines with attempt_id and avoids temp dir titles', () => {
    const attemptId = 'worker_0-https://www.royalroad.com/fiction/12345-1719283921000'
    const workerLogs = [
        {
            timestamp: '2026-10-28 12:00:00',
            level: 'info',
            message: '(royalroad) Processing https://www.royalroad.com/fiction/12345',
            thread_site: 'royalroad',
            story_url: 'https://www.royalroad.com/fiction/12345',
            worker_id: 'worker_0',
            attempt_id: attemptId,
        },
        {
            timestamp: '2026-10-28 12:00:01',
            level: 'info',
            message: "(royalroad) Using temp directory: '/tmp/tmpcan0oqrg'",
            thread_site: 'royalroad',
            story_url: 'https://www.royalroad.com/fiction/12345',
            worker_id: 'worker_0',
            attempt_id: attemptId,
        },
        {
            timestamp: '2026-10-28 12:00:02',
            level: 'debug',
            message: "Executing FanFicFare directly: /tmp/tmpcan0oqrg/The Bee Dungeon.epub",
            worker_id: 'worker_0',
            story_url: 'https://www.royalroad.com/fiction/12345',
            attempt_id: attemptId,
        },
        {
            timestamp: '2026-10-28 12:00:05',
            level: 'info',
            message: "(royalroad) Successfully processed The Bee Dungeon",
            thread_site: 'royalroad',
            story_url: 'https://www.royalroad.com/fiction/12345',
            story_title: 'The Bee Dungeon',
            worker_id: 'worker_0',
            attempt_id: attemptId,
        },
        {
            timestamp: '2026-10-28 12:00:06',
            level: 'info',
            message: "Apprise notification for 'New Fanfiction Download': 'The Bee Dungeon' sent successfully to 1 target",
            thread_site: 'royalroad',
            story_url: 'https://www.royalroad.com/fiction/12345',
            story_title: 'The Bee Dungeon',
            worker_id: 'worker_0',
            attempt_id: attemptId,
        },
    ]

    const blocks = buildLogAttemptBlocks(workerLogs)
    assert.equal(blocks.length, 1)

    const block = blocks[0]
    assert.equal(block.kind, 'story_attempt')
    assert.equal(block.title, 'The Bee Dungeon')
    assert.notEqual(block.title, '/tmp/tmpcan0oqrg')
    assert.equal(block.lines.length, 5)
    assert.equal(block.status, 'success')
    assert.equal(block.isActive, false)
})

test('buildLogAttemptBlocks handles newest-first logs with identical timestamps without splitting startup block', () => {
    // Reverse chronological logs (newest first, identical second), with sequence numbers
    const newestFirstLogs = [
        { seq: 6, timestamp: '2026-10-28 06:45:29 PM', level: 'info', message: 'WebServer: Starting on 0.0.0.0:8080' },
        { seq: 5, timestamp: '2026-10-28 06:45:29 PM', level: 'info', message: 'All processes started successfully' },
        { seq: 4, timestamp: '2026-10-28 06:45:29 PM', level: 'info', message: 'Worker worker_0 started' },
        { seq: 3, timestamp: '2026-10-28 06:45:29 PM', level: 'info', message: '------------------------------' },
        { seq: 2, timestamp: '2026-10-28 06:45:29 PM', level: 'info', message: '--- Configuration Details ---' },
        { seq: 1, timestamp: '2026-10-28 06:45:29 PM', level: 'info', message: 'Starting AutomatedFanfic v6.15.1' },
    ]

    const blocks = buildLogAttemptBlocks(newestFirstLogs)
    assert.equal(blocks.length, 1)
    assert.equal(blocks[0].kind, 'system')
    assert.equal(blocks[0].title, 'Application Startup & Lifecycle')
    assert.equal(blocks[0].lines.length, 6)
    // Order inside the block must be chronological (seq 1 first, seq 6 last)
    assert.equal(blocks[0].lines[0].message, 'Starting AutomatedFanfic v6.15.1')
    assert.equal(blocks[0].lines[5].message, 'WebServer: Starting on 0.0.0.0:8080')
})

test('buildLogAttemptBlocks populates historical story attempts from knownDownloads (history.db)', () => {
    const historicalDownloads = [
        {
            url: 'https://archiveofourown.org/works/99887766',
            title: 'Chronicles of the Multiverse',
            site: 'archiveofourown',
            status: 'success',
            completed_at: '2026-10-28 14:00:00',
        },
        {
            url: 'https://www.fanfiction.net/s/11223344/1/',
            title: 'Shadows in the Mist',
            site: 'fanfiction',
            status: 'failed',
            error_message: 'HTTP 404: Story Not Found',
            completed_at: '2026-10-28 14:30:00',
        },
    ]

    const blocks = buildLogAttemptBlocks([], historicalDownloads)
    assert.equal(blocks.length, 2)
    const ao3 = blocks.find((b) => b.url === 'https://archiveofourown.org/works/99887766')
    assert.ok(ao3)
    assert.equal(ao3?.title, 'Chronicles of the Multiverse')
    assert.equal(ao3?.status, 'success')
    assert.equal(ao3?.isActive, false)

    const ffn = blocks.find((b) => b.url === 'https://www.fanfiction.net/s/11223344/1/')
    assert.ok(ffn)
    assert.equal(ffn?.title, 'Shadows in the Mist')
    assert.equal(ffn?.status, 'failed')
    assert.equal(ffn?.traceback, 'HTTP 404: Story Not Found')
})

test('computeDirtySections tracks unsaved changes across all config sections and personal.ini', () => {
    const initCfg = {
        email: { mailbox: 'INBOX', sleep_time: 60 },
        calibre: { update_only: false },
    }
    const curCfg = {
        email: { mailbox: 'Alerts', sleep_time: 60 },
        calibre: { update_only: false },
    }
    const dirty = computeDirtySections(curCfg, initCfg, '[defaults]\nis_adult:true', '[defaults]\nis_adult:false')
    assert.deepEqual(dirty.email, ['mailbox'])
    assert.equal(dirty.calibre, undefined)
    assert.deepEqual(dirty['personal.ini'], ['content'])
})

test('getStatusColor maps semantic statuses to canonical hex colors', () => {
    assert.equal(getStatusColor('success'), STATUS_COLORS.success)
    assert.equal(getStatusColor('failed'), STATUS_COLORS.failed)
    assert.equal(getStatusColor('abandoned'), STATUS_COLORS.abandoned)
    assert.equal(getStatusColor('waiting'), STATUS_COLORS.waiting)
})

test('buildTimelineBuckets creates 24 hourly buckets for 24h and 7 daily buckets for 7d', () => {
    const now = Date.now()
    const sampleDownloads = [
        {
            url: 'https://archiveofourown.org/works/1',
            site: 'archiveofourown',
            title: 'One',
            calibre_id: '101',
            status: 'success',
            error_message: null,
            started_at: new Date(now - 30 * 60 * 1000).toISOString(),
            completed_at: new Date(now - 29 * 60 * 1000).toISOString(),
        },
    ]
    const b24 = buildTimelineBuckets(sampleDownloads, '24h', now)
    assert.equal(b24.length, 24)
    assert.equal(b24.reduce((acc, p) => acc + p.success, 0), 1)

    const b7 = buildTimelineBuckets(sampleDownloads, '7d', now)
    assert.equal(b7.length, 7)
    assert.equal(b7.reduce((acc, p) => acc + p.success, 0), 1)

    const filtered24 = filterDownloadsByPeriod(sampleDownloads, '24h', now)
    assert.equal(filtered24.length, 1)
})

test('scrubPiiFromLogText detects and redacts emails, tokens, cookies, paths, IPs, and optional story URLs', () => {
    const raw = [
        'UrlIngester: Authenticated as reader.jane@gmail.com from 192.168.1.44 (local 127.0.0.1)',
        'Cookiejar: cf_clearance=secret_cf_cookie_998877; session_id:abc123xyz',
        'Pushbullet token o.AbCdEfGhIjKlMnOpQrSt1234 loaded from /Users/jane/Library/Calibre',
        'Story https://archiveofourown.org/works/999999 titled Secret Starlight',
    ].join('\n')

    const res = scrubPiiFromLogText(raw, { redactStoryUrls: true, storyTitle: 'Secret Starlight' })
    assert.equal(res.redactionCount >= 7, true)
    assert.equal(res.text.includes('reader.jane@gmail.com'), false)
    assert.equal(res.text.includes('[REDACTED_EMAIL]'), true)
    assert.equal(res.text.includes('192.168.1.44'), false)
    assert.equal(res.text.includes('127.0.0.1'), true)
    assert.equal(res.text.includes('secret_cf_cookie_998877'), false)
    assert.equal(res.text.includes('cf_clearance=[REDACTED]'), true)
    assert.equal(res.text.includes('o.[REDACTED_TOKEN]'), true)
    assert.equal(res.text.includes('/Users/[REDACTED_USER]/Library/Calibre'), true)
    assert.equal(res.text.includes('[REDACTED_STORY_URL]'), true)
    assert.equal(res.text.includes('[REDACTED_STORY_TITLE]'), true)
})

test('buildGitHubIssueDraft includes startup logs and supports story redaction', () => {
    const draft = buildGitHubIssueDraft({
        block: {
            id: 'attempt-1',
            kind: 'story_attempt',
            site: 'fanfiction',
            url: 'https://www.fanfiction.net/s/13904512/1/',
            title: 'The Winds of Time',
            attemptNumber: 2,
            status: 'failed',
            isActive: true,
            activeStage: 'waiting_retry',
            startedAt: '2025-05-12 14:20:01',
            endedAt: '2025-05-12 14:20:10',
            lines: [
                {
                    timestamp: '2025-05-12 14:20:01',
                    level: 'ERROR',
                    message: '(fanfiction) Failed for user test.user@example.com with cf_clearance=my_secret_token',
                },
            ],
            traceback: 'Traceback (most recent call last):\n  File "/home/alice/fanfic/worker.py", line 42\nHTTPError: 403',
        },
        startupLogs: [
            { timestamp: '2025-05-12 14:00:01', level: 'info', message: 'Supervisor: Starting AutomatedFanfic process tree...' },
        ],
        scrubPii: true,
    })

    assert.equal(draft.title, '[Bug] (fanfiction) Download failure: The Winds of Time')
    assert.equal(draft.detectedPiiCount, 3)
    assert.equal(draft.body.includes('[REDACTED_EMAIL]'), true)
    assert.equal(draft.body.includes('cf_clearance=[REDACTED]'), true)
    assert.equal(draft.body.includes('/home/[REDACTED_USER]/fanfic/worker.py'), true)
    assert.equal(draft.body.includes('### Startup Log & Environment Context'), true)
    assert.equal(draft.body.includes('Supervisor: Starting AutomatedFanfic process tree...'), true)

    const { url, isTruncated } = buildGitHubIssueUrl({
        repo: 'AutomatedFanfic/AutomatedFanfic',
        title: draft.title,
        body: draft.body,
        labels: ['bug'],
    })
    assert.equal(isTruncated, false)
    assert.equal(url.startsWith('https://github.com/AutomatedFanfic/AutomatedFanfic/issues/new?'), true)
    assert.equal(url.includes('labels=bug'), true)
})

test('diagnoseErrorSignature identifies Cloudflare, 404, Auth, and Calibre errors', () => {
    const cf = diagnoseErrorSignature('HTTP 503: Cloudflare anti-bot challenge encountered')
    assert.equal(cf?.category, 'Anti-Bot / Cloudflare Challenge')
    assert.equal(cf?.configTab, 'personal.ini')

    const nf = diagnoseErrorSignature('Story has been removed or restricted by author (HTTP 404 Not Found)')
    assert.equal(nf?.category, 'Story Removed or Restricted (404)')

    const cal = diagnoseErrorSignature('Calibre database is locked by another process')
    assert.equal(cal?.category, 'Calibre Library Target Error')
    assert.equal(cal?.configTab, 'calibre')
})

test('computeIniLineDiff and extractIniSections parse INI changes and headers', () => {
    const sections = extractIniSections('[defaults]\nis_adult:true\n[epub]\ninclude_images:true')
    assert.equal(sections.length, 2)
    assert.equal(sections[0].name, 'defaults')
    assert.equal(sections[1].name, 'epub')

    const diff = computeIniLineDiff('[defaults]\nis_adult:false', '[defaults]\nis_adult:true')
    assert.equal(diff.some((d) => d.type === 'remove' && d.text.includes('false')), true)
    assert.equal(diff.some((d) => d.type === 'add' && d.text.includes('true')), true)
})

test('extractSystemVersionsFromLogs and buildGitHubIssueDraft include environment & component versions', () => {
    const startupLogs = [
        { timestamp: '2026-10-28 10:00:00', level: 'info', message: 'Starting AutomatedFanfic v6.14.0' },
        { timestamp: '2026-10-28 10:00:01', level: 'info', message: 'Python version: 3.13.2 (CPython)' },
        { timestamp: '2026-10-28 10:00:01', level: 'info', message: 'OS / Platform: Linux-6.6.137-aarch64 [Docker container]' },
        { timestamp: '2026-10-28 10:00:02', level: 'info', message: 'Calibre version: 7.26.0' },
        { timestamp: '2026-10-28 10:00:02', level: 'info', message: 'FanFicFare version: 4.44.0' },
        { timestamp: '2026-10-28 10:00:03', level: 'info', message: 'Apprise version: 1.9.0' },
    ]

    const versions = extractSystemVersionsFromLogs(startupLogs)
    assert.equal(versions.automatedfanfic, '6.14.0')
    assert.equal(versions.python, '3.13.2 (CPython)')
    assert.equal(versions.platform, 'Linux-6.6.137-aarch64 [Docker container]')
    assert.equal(versions.calibre, '7.26.0')
    assert.equal(versions.fanficfare, '4.44.0')
    assert.equal(versions.apprise, '1.9.0')

    const draft = buildGitHubIssueDraft({
        startupLogs,
        block: {
            id: 'err-1',
            kind: 'story_attempt',
            site: 'royalroad',
            url: 'https://royalroad.com/fiction/12345',
            title: 'Test Story',
            attemptNumber: 1,
            status: 'failed',
            isActive: false,
            startedAt: '2026-10-28 10:05:00',
            endedAt: '2026-10-28 10:05:05',
            lines: [{ timestamp: '2026-10-28 10:05:02', level: 'error', message: 'Download failed' }],
            traceback: 'Traceback: something failed in worker',
        },
    })

    assert.ok(draft.body.includes('### Environment & Component Versions'))
    assert.ok(draft.body.includes('- **AutomatedFanfic**: `v6.14.0`'))
    assert.ok(draft.body.includes('- **Python**: `3.13.2 (CPython)`'))
    assert.ok(draft.body.includes('- **FanFicFare**: `4.44.0`'))
    assert.ok(draft.body.includes('- **Calibre**: `7.26.0`'))
    assert.ok(draft.body.includes('- **Apprise**: `1.9.0`'))
})
