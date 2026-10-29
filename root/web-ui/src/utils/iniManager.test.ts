import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
    parseIniDocument,
    serializeIniDocument,
    updateSectionField,
    removeSectionField,
    detectFlareSolverr,
    setFlareSolverrConfig,
    setSiteFlareSolverrConfig,
    getSectionFlareSolverr,
    getAllFlareSolverrSites,
    addIniSection,
    removeIniSection,
    updateSectionContent,
    categorizeIniSection,
    isSectionHeader,
    extractReferenceSections,
    extractReferenceKeyComments,
    extractReferenceKeyDefinitions,
    getSettingSuggestions,
} from './iniManager.ts'

const SAMPLE_INI = `## Global preamble comments
## AutomatedFanfic test personal.ini

[defaults]
is_adult:true
always_overwrite: true
output_filename: \${title}-\${author}-\${siteabbrev}_\${storyId}\${formatext}

[epub]
include_images:true
keep_summary_html:true
make_firstimage_cover:true
add_to_replace_metadata:
 oneshot=>Completed=>Completed\\,Oneshot&&numChapters=>^1$

[www.fanfiction.net]
username: testuser
password: secretpassword
`

test('isSectionHeader correctly identifies section brackets', () => {
    assert.equal(isSectionHeader('[defaults]'), 'defaults')
    assert.equal(isSectionHeader('  [www.fanfiction.net]  '), 'www.fanfiction.net')
    assert.equal(isSectionHeader('is_adult:true'), null)
    assert.equal(isSectionHeader('# [commented_section]'), null)
})

test('parseIniDocument parses preamble and structured sections', () => {
    const doc = parseIniDocument(SAMPLE_INI)
    assert.ok(doc.preamble.includes('AutomatedFanfic test personal.ini'))
    assert.equal(doc.sections.length, 3)

    const [defaultsSec, epubSec, ffnSec] = doc.sections
    assert.equal(defaultsSec.name, 'defaults')
    assert.equal(defaultsSec.fields.length, 3)
    assert.equal(defaultsSec.fields[0].key, 'is_adult')
    assert.equal(defaultsSec.fields[0].value, 'true')

    assert.equal(epubSec.name, 'epub')
    assert.equal(epubSec.fields.length, 4)
    assert.ok(epubSec.fields.some((f) => f.key === 'add_to_replace_metadata'))
    assert.ok(epubSec.customDirectives.includes('oneshot=>Completed'))

    assert.equal(ffnSec.name, 'www.fanfiction.net')
    assert.equal(ffnSec.fields.length, 2)
})

test('serializeIniDocument accurately recreates INI file', () => {
    const doc = parseIniDocument(SAMPLE_INI)
    const serialized = serializeIniDocument(doc)

    assert.ok(serialized.includes('[defaults]'))
    assert.ok(serialized.includes('is_adult:true'))
    assert.ok(serialized.includes('[epub]'))
    assert.ok(serialized.includes('[www.fanfiction.net]'))
})

test('updateSectionField modifies existing field or appends new one', () => {
    const lines = ['is_adult:true', 'make_directories:true']
    const updated = updateSectionField(lines, 'is_adult', 'false')
    assert.deepEqual(updated, ['is_adult:false', 'make_directories:true'])

    const appended = updateSectionField(updated, 'new_setting', 'hello')
    assert.deepEqual(appended, ['is_adult:false', 'make_directories:true', 'new_setting:hello'])
})

test('removeSectionField deletes field case-insensitively', () => {
    const lines = ['is_adult:true', 'make_directories:true']
    const removed = removeSectionField(lines, 'IS_ADULT')
    assert.deepEqual(removed, ['make_directories:true'])
})

test('detectFlareSolverr finds enabled or disabled proxy settings', () => {
    const disabled = detectFlareSolverr(SAMPLE_INI)
    assert.equal(disabled.isConfigured, false)
    assert.equal(disabled.isEnabled, false)

    const withFlare = `${SAMPLE_INI}
[defaults]
use_flaresolverr_proxy:true
flaresolverr_proxy_address:http://127.0.0.1:8191/v1
`
    const active = detectFlareSolverr(withFlare)
    assert.equal(active.isConfigured, true)
    assert.equal(active.isEnabled, true)
    assert.equal(active.address, 'http://127.0.0.1:8191/v1')
    assert.equal(active.section, 'defaults')
})

test('setFlareSolverrConfig adds, enables, disables, and removes FlareSolverr proxy', () => {
    // 1. Enable FlareSolverr in 1 click
    const enabledIni = setFlareSolverrConfig(SAMPLE_INI, true, 'http://localhost:8191/v1')
    const status1 = detectFlareSolverr(enabledIni)
    assert.equal(status1.isEnabled, true)
    assert.equal(status1.address, 'http://localhost:8191/v1')

    // 2. Disable FlareSolverr
    const disabledIni = setFlareSolverrConfig(enabledIni, false)
    const status2 = detectFlareSolverr(disabledIni)
    assert.equal(status2.isEnabled, false)
    assert.equal(status2.isConfigured, true)

    // 3. Remove completely
    const removedIni = setFlareSolverrConfig(enabledIni, false, undefined, true)
    const status3 = detectFlareSolverr(removedIni)
    assert.equal(status3.isConfigured, false)
    assert.equal(status3.isEnabled, false)
})

test('setSiteFlareSolverrConfig injects proxy on per-site basis without touching [defaults]', () => {
    // Inject FlareSolverr specifically on www.fanfiction.net
    const siteConfigured = setSiteFlareSolverrConfig(
        SAMPLE_INI,
        'www.fanfiction.net',
        true,
        'http://127.0.0.1:8191/v1'
    )

    const doc = parseIniDocument(siteConfigured)
    const defaultsSec = doc.sections.find((s) => s.name === 'defaults')
    const ffnSec = doc.sections.find((s) => s.name === 'www.fanfiction.net')

    assert.ok(defaultsSec)
    assert.ok(ffnSec)

    // Verify [defaults] does NOT contain use_flaresolverr_proxy
    const defaultsFlare = getSectionFlareSolverr(defaultsSec.lines, 'defaults')
    assert.equal(defaultsFlare.isConfigured, false)
    assert.equal(defaultsFlare.isEnabled, false)

    // Verify [www.fanfiction.net] DOES contain use_flaresolverr_proxy
    const ffnFlare = getSectionFlareSolverr(ffnSec.lines, 'www.fanfiction.net')
    assert.equal(ffnFlare.isConfigured, true)
    assert.equal(ffnFlare.isEnabled, true)
    assert.equal(ffnFlare.address, 'http://127.0.0.1:8191/v1')

    // Verify getAllFlareSolverrSites finds the configured site
    const allSites = getAllFlareSolverrSites(siteConfigured)
    assert.equal(allSites.length, 1)
    assert.equal(allSites[0].section, 'www.fanfiction.net')

    // Disable on site
    const disabledSite = setSiteFlareSolverrConfig(siteConfigured, 'www.fanfiction.net', false)
    const disabledDoc = parseIniDocument(disabledSite)
    const disabledFfn = disabledDoc.sections.find((s) => s.name === 'www.fanfiction.net')
    assert.ok(disabledFfn)
    const disabledFlare = getSectionFlareSolverr(disabledFfn.lines, 'www.fanfiction.net')
    assert.equal(disabledFlare.isEnabled, false)
    assert.equal(disabledFlare.isConfigured, true)
})

test('addIniSection and removeIniSection modify section list safely', () => {
    const withAo3 = addIniSection(SAMPLE_INI, 'archiveofourown.org', 'is_adult:true\nslow_down_sleep_time:2')
    const doc = parseIniDocument(withAo3)
    assert.ok(doc.sections.some((s) => s.name === 'archiveofourown.org'))

    // Adding existing section should be a no-op
    const duplicateAdd = addIniSection(withAo3, 'archiveofourown.org')
    assert.equal(duplicateAdd, withAo3)

    // Remove section
    const removed = removeIniSection(withAo3, 'archiveofourown.org')
    const docAfter = parseIniDocument(removed)
    assert.ok(!docAfter.sections.some((s) => s.name === 'archiveofourown.org'))
})

test('updateSectionContent updates scoped section lines', () => {
    const updated = updateSectionContent(SAMPLE_INI, 'defaults', 'is_adult:false\nalways_overwrite:false')
    const doc = parseIniDocument(updated)
    const defaultsSec = doc.sections.find((s) => s.name === 'defaults')
    assert.ok(defaultsSec)
    assert.equal(defaultsSec.lines.length, 2)
    assert.equal(defaultsSec.lines[0], 'is_adult:false')
})

test('categorizeIniSection categorizes section names properly', () => {
    assert.equal(categorizeIniSection('defaults').category, 'defaults')
    assert.equal(categorizeIniSection('epub').category, 'format')
    assert.equal(categorizeIniSection('www.fanfiction.net').category, 'site')
    assert.equal(categorizeIniSection('archiveofourown.org').category, 'site')
    assert.equal(categorizeIniSection('base_xenforoforum').category, 'adapter')
    assert.equal(categorizeIniSection('my_custom_override').category, 'format')
})

test('extractReferenceSections and extractReferenceKeyComments extract metadata algorithmically', () => {
    const reference = `## Core defaults
## Confirm adult content
is_adult:true

[epub]
## Enable images in epub
include_images:true

[royalroad.com]
slow_down_sleep_time:2
`
    const sections = extractReferenceSections(reference)
    assert.deepEqual(sections, ['epub', 'royalroad.com'])

    const comments = extractReferenceKeyComments(reference)
    assert.ok(comments['is_adult'].includes('Confirm adult content'))
    assert.ok(comments['include_images'].includes('Enable images in epub'))
})

test('extractReferenceKeyDefinitions and getSettingSuggestions provide accurate autocomplete options', () => {
    const reference = `[defaults]
## Confirm adult content
is_adult:false
## Seconds between downloads
slow_down_sleep_time:20
#username:
#password:

[www.fanfiction.net]
## Enable Cloudflare bypass proxy
#use_flaresolverr_proxy:true
#flaresolverr_proxy_address:localhost
`
    const defs = extractReferenceKeyDefinitions(reference)
    assert.equal(defs.length, 6)

    const adultDef = defs.find((d) => d.key === 'is_adult')
    assert.ok(adultDef)
    assert.equal(adultDef.defaultValue, 'false')
    assert.ok(adultDef.description?.includes('Confirm adult content'))

    const flareDef = defs.find((d) => d.key === 'use_flaresolverr_proxy')
    assert.ok(flareDef)
    assert.equal(flareDef.section, 'www.fanfiction.net')
    assert.equal(flareDef.defaultValue, 'true')

    // Suggestions for www.fanfiction.net when is_adult is already present
    const existing = new Set(['is_adult'])
    const suggestions = getSettingSuggestions(defs, 'www.fanfiction.net', existing, '')
    // is_adult must be excluded
    assert.ok(!suggestions.some((s) => s.key === 'is_adult'))
    // www.fanfiction.net section keys must come first
    assert.equal(suggestions[0].section, 'www.fanfiction.net')
    assert.ok(suggestions.some((s) => s.key === 'use_flaresolverr_proxy'))

    // Query filter
    const querySuggestions = getSettingSuggestions(defs, 'defaults', new Set(), 'sleep')
    assert.equal(querySuggestions.length, 1)
    assert.equal(querySuggestions[0].key, 'slow_down_sleep_time')
    assert.equal(querySuggestions[0].defaultValue, '20')
})
