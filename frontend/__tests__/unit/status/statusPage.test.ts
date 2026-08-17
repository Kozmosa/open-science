import { describe, expect, it } from 'vitest'

import {
  aggregateBars,
  buildBars,
  collectEvents,
  newestResult,
  overallTone,
  parseStatusLocale,
  parseStatusTheme,
  parseUptime,
  resultTone,
  type ComponentStatus,
  type GatusResult,
} from '../../../src/status/model'

const result = (success: boolean, timestamp: string, status = 200): GatusResult => ({
  success,
  timestamp,
  status,
  duration: 12_000_000,
})

const component = (tone: ComponentStatus['tone'], results: GatusResult[]): ComponentStatus => ({
  key: 'production_api',
  name: 'Backend API',
  group: 'Production',
  results,
  events: [],
  uptime: 99.9,
  latest: newestResult(results),
  tone,
})

describe('status page model', () => {
  it('normalizes stored and DOM preference values at the status model interface', () => {
    expect(parseStatusLocale('en')).toBe('en')
    expect(parseStatusLocale('zh-CN')).toBe('zh-CN')
    expect(parseStatusLocale('fr')).toBe('en')
    expect(parseStatusLocale(null)).toBe('en')

    expect(parseStatusTheme('light')).toBe('light')
    expect(parseStatusTheme('dark')).toBe('dark')
    expect(parseStatusTheme('system')).toBe('system')
    expect(parseStatusTheme('sepia')).toBe('system')
    expect(parseStatusTheme(undefined)).toBe('system')
  })

  it('selects the newest result independently of API ordering', () => {
    const older = result(true, '2026-08-02T00:00:00Z')
    const newer = result(false, '2026-08-02T00:01:00Z', 503)
    expect(newestResult([older, newer])).toBe(newer)
  })

  it('treats stale checks as unknown and failed 5xx checks as outages', () => {
    const now = Date.parse('2026-08-02T00:04:00Z')
    expect(resultTone(result(false, '2026-08-02T00:03:00Z', 503), now)).toBe('outage')
    expect(resultTone(result(true, '2026-08-01T23:00:00Z'), now)).toBe('unknown')
  })

  it('uses the most severe component for the overall state', () => {
    expect(overallTone([component('healthy', []), component('degraded', [])])).toBe('degraded')
    expect(overallTone([component('healthy', []), component('outage', [])])).toBe('outage')
    expect(overallTone([])).toBe('unknown')
  })

  it('pads sparse histories and aggregates failures across components', () => {
    const healthy = component('healthy', [result(true, '2026-08-02T00:00:00Z')])
    const outage = component('outage', [result(false, '2026-08-02T00:00:00Z', 503)])
    expect(buildBars(healthy.results, 3)).toEqual([null, null, 'healthy'])
    expect(aggregateBars([healthy, outage], 3)).toEqual([null, null, 'outage'])
  })

  it('clamps uptime and converts endpoint events to a newest-first timeline', () => {
    const item = component('healthy', [])
    item.events = [
      { type: 'START', timestamp: '2026-08-01T00:00:00Z' },
      { type: 'UNHEALTHY', timestamp: '2026-08-01T01:00:00Z' },
      { type: 'HEALTHY', timestamp: '2026-08-01T02:00:00Z' },
    ]
    expect(parseUptime('101.5')).toBe(100)
    expect(parseUptime('0.999669')).toBeCloseTo(99.9669)
    expect(parseUptime('99.5')).toBe(99.5)
    expect(collectEvents([item]).map((event) => event.type)).toEqual(['HEALTHY', 'UNHEALTHY'])
  })
})
