import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
    parseIniDocument,
    serializeIniDocument,
    updateSectionField,
    removeSectionField,
    detectFlareSolverr,
    setFlareSolverrConfig,
    addIniSection,
    removeIniSection,
    updateSectionContent,
    categorizeIniSection,
    isSectionHeader,
    extractReferenceSections,
    extractReferenceKeyComments,
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
