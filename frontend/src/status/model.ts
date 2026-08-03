export type StatusTone = 'healthy' | 'degraded' | 'outage' | 'unknown'

export interface GatusConditionResult {
  condition: string
  success: boolean
}

export interface GatusResult {
  status?: number
  duration: number
  errors?: string[]
  conditionResults?: GatusConditionResult[]
  success: boolean
  timestamp: string
}

export interface GatusEvent {
  type: 'START' | 'HEALTHY' | 'UNHEALTHY'
  timestamp: string
}

export interface GatusEndpoint {
  name: string
  group?: string
  key: string
  results: GatusResult[]
  events?: GatusEvent[]
}

export interface ComponentStatus extends GatusEndpoint {
  uptime: number | null
  tone: StatusTone
  latest: GatusResult | null
}

export interface StatusEvent {
  component: string
  type: GatusEvent['type']
  timestamp: Date
}

const CURRENT_RESULT_MAX_AGE_MS = 5 * 60 * 1000

export function newestResult(results: GatusResult[]): GatusResult | null {
  return [...results].sort(
    (left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp),
  )[0] ?? null
}

export function resultTone(result: GatusResult | null, now = Date.now()): StatusTone {
  if (!result || Number.isNaN(Date.parse(result.timestamp))) {
    return 'unknown'
  }
  if (now - Date.parse(result.timestamp) > CURRENT_RESULT_MAX_AGE_MS) {
    return 'unknown'
  }
  if (result.success) {
    return 'healthy'
  }
  if ((result.status ?? 0) >= 500 || (result.status ?? 0) === 0) {
    return 'outage'
  }
  return 'degraded'
}

export function overallTone(components: ComponentStatus[]): StatusTone {
  if (!components.length || components.some((component) => component.tone === 'unknown')) {
    return 'unknown'
  }
  if (components.some((component) => component.tone === 'outage')) {
    return 'outage'
  }
  if (components.some((component) => component.tone === 'degraded')) {
    return 'degraded'
  }
  return 'healthy'
}

export function parseUptime(value: string): number | null {
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? Math.min(100, Math.max(0, parsed)) : null
}

export function formatUptime(value: number | null): string {
  if (value === null) {
    return 'No uptime data'
  }
  return `${value.toFixed(2)}% uptime`
}

export function resultDurationMs(result: GatusResult | null): number | null {
  if (!result || !Number.isFinite(result.duration)) {
    return null
  }
  return Math.round(result.duration / 1_000_000)
}

export function buildBars(results: GatusResult[], count = 90): Array<StatusTone | null> {
  const tones = [...results]
    .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp))
    .slice(-count)
    .map((result) => resultTone(result, Date.parse(result.timestamp)))
  return [...Array<StatusTone | null>(Math.max(0, count - tones.length)).fill(null), ...tones]
}

export function aggregateBars(
  components: ComponentStatus[],
  count = 90,
): Array<StatusTone | null> {
  if (!components.length) {
    return Array<null>(count).fill(null)
  }
  const componentBars = components.map((component) => buildBars(component.results, count))
  return Array.from({ length: count }, (_, index) => {
    const values = componentBars.map((bars) => bars[index]).filter(Boolean) as StatusTone[]
    if (!values.length) return null
    if (values.includes('outage')) return 'outage'
    if (values.includes('degraded')) return 'degraded'
    if (values.includes('unknown')) return 'unknown'
    return 'healthy'
  })
}

export function collectEvents(components: ComponentStatus[]): StatusEvent[] {
  return components
    .flatMap((component) =>
      (component.events ?? [])
        .filter((event) => event.type !== 'START')
        .map((event) => ({
          component: component.name,
          type: event.type,
          timestamp: new Date(event.timestamp),
        })),
    )
    .filter((event) => !Number.isNaN(event.timestamp.getTime()))
    .sort((left, right) => right.timestamp.getTime() - left.timestamp.getTime())
}

export function monthLabel(date: Date, locale: string): string {
  return new Intl.DateTimeFormat(locale, { month: 'short', year: 'numeric' }).format(date)
}

export function periodLabel(date: Date, locale: string): string {
  const start = new Date(date.getFullYear(), date.getMonth() - 3, 1)
  return `${monthLabel(start, locale)} - ${monthLabel(date, locale)}`
}
