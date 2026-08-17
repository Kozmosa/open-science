import './styles.css'

import {
  aggregateBars,
  buildBars,
  collectEvents,
  formatUptime,
  monthLabel,
  newestResult,
  overallTone,
  parseStatusLocale,
  parseStatusTheme,
  parseUptime,
  resultDurationMs,
  resultTone,
  type ComponentStatus,
  type GatusEndpoint,
  type StatusEvent,
  type StatusLocale,
  type StatusTheme,
  type StatusTone,
} from './model'

const translations = {
  en: {
    subscribe: 'Subscribe to updates',
    language: 'Switch language',
    theme: 'Toggle theme',
    healthyTitle: 'Everything is running smoothly',
    healthyBody: 'All systems are operating as expected.',
    degradedTitle: 'Some systems are experiencing issues',
    degradedBody: 'We are investigating degraded service performance.',
    outageTitle: 'Some systems are currently unavailable',
    outageBody: 'We are working to restore normal service.',
    unknownTitle: 'Status is temporarily unavailable',
    unknownBody: 'Live monitoring data could not be loaded. Please try again shortly.',
    systemStatus: 'System status',
    infrastructure: 'Infrastructure',
    components: 'components',
    live: 'Live monitoring',
    uptimeWindow: '30-day uptime',
    eventCalendar: 'Event calendar',
    historicalEvents: 'View historical events',
    noEvents: 'No status changes have been recorded for this period.',
    latestCheck: 'Latest check',
    responseTime: 'Response time',
    statusHealthy: 'Operational',
    statusDegraded: 'Degraded performance',
    statusOutage: 'Service outage',
    statusUnknown: 'No current data',
    subscribeTitle: 'Status updates',
    subscribeBody: 'This page refreshes automatically every 30 seconds. Notification subscriptions are not configured yet.',
    historyTitle: 'Historical events',
    close: 'Close',
  },
  'zh-CN': {
    subscribe: '订阅状态更新',
    language: '切换语言',
    theme: '切换主题',
    healthyTitle: '所有系统运行正常',
    healthyBody: '各项服务均按预期运行。',
    degradedTitle: '部分系统出现异常',
    degradedBody: '我们正在调查服务性能下降的问题。',
    outageTitle: '部分系统暂时不可用',
    outageBody: '我们正在努力恢复正常服务。',
    unknownTitle: '暂时无法获取系统状态',
    unknownBody: '实时监控数据加载失败，请稍后重试。',
    systemStatus: '系统状态',
    infrastructure: '基础设施',
    components: '个组件',
    live: '实时监测',
    uptimeWindow: '近 30 天可用性',
    eventCalendar: '事件日历',
    historicalEvents: '查看历史事件',
    noEvents: '当前时段没有记录到状态变化。',
    latestCheck: '最近检查',
    responseTime: '响应时间',
    statusHealthy: '运行正常',
    statusDegraded: '性能下降',
    statusOutage: '服务中断',
    statusUnknown: '暂无当前数据',
    subscribeTitle: '状态更新',
    subscribeBody: '本页面每 30 秒自动刷新，目前尚未配置通知订阅。',
    historyTitle: '历史事件',
    close: '关闭',
  },
} as const

const primaryNames = new Set(['Web App', 'Backend API'])
const root = document.querySelector<HTMLDivElement>('#status-root')
if (!root) throw new Error('Status page root is missing')

let locale: StatusLocale = parseStatusLocale(localStorage.getItem('openscience-status-locale'))
let theme: StatusTheme = parseStatusTheme(localStorage.getItem('openscience-status-theme'))
let components: ComponentStatus[] = []
let events: StatusEvent[] = []
let selectedMonth = new Date()
let openModal: { title: string; description: string; events: StatusEvent[] } | null = null
let hasPainted = false

const icon = (name: 'check' | 'alert' | 'info' | 'left' | 'right' | 'down' | 'calendar' | 'bell' | 'language' | 'sun' | 'close') => {
  const paths = {
    check: '<path d="M20 6 9 17l-5-5"/>',
    alert: '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    left: '<path d="m15 18-6-6 6-6"/>',
    right: '<path d="m9 18 6-6-6-6"/>',
    down: '<path d="m6 9 6 6 6-6"/>',
    calendar: '<path d="M8 2v4M16 2v4M3 10h18"/><rect width="18" height="18" x="3" y="4" rx="2"/>',
    bell: '<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0M18 8A6 6 0 0 0 6 8c0 7-3 7-3 9h18c0-2-3-2-3-9"/>',
    language: '<path d="m5 8 6 6M4 14l6-7 2-3M2 5h12M7 2h1"/><path d="m22 22-5-10-5 10M14 18h6"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    close: '<path d="M18 6 6 18M6 6l12 12"/>',
  }
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[character] ?? character)
}

function applyTheme(): void {
  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0a0a0a' : '#ffffff')
}

function statusCopy(tone: StatusTone): { title: string; body: string } {
  const t = translations[locale]
  if (tone === 'healthy') return { title: t.healthyTitle, body: t.healthyBody }
  if (tone === 'degraded') return { title: t.degradedTitle, body: t.degradedBody }
  if (tone === 'outage') return { title: t.outageTitle, body: t.outageBody }
  return { title: t.unknownTitle, body: t.unknownBody }
}

function toneLabel(tone: StatusTone): string {
  const t = translations[locale]
  return {
    healthy: t.statusHealthy,
    degraded: t.statusDegraded,
    outage: t.statusOutage,
    unknown: t.statusUnknown,
  }[tone]
}

function statusDot(tone: StatusTone): string {
  return `<span class="status-dot ${tone}" aria-hidden="true">${icon(tone === 'healthy' ? 'check' : 'alert')}</span>`
}

function renderBars(tones: Array<StatusTone | null>, label: string): string {
  return `<div class="bars" role="img" aria-label="${escapeHtml(label)}">${tones.map((tone, index) => `<span class="bar ${tone ?? 'unknown'}" style="--bar-index: ${index}"></span>`).join('')}</div>`
}

function componentDescription(component: ComponentStatus): string {
  const t = translations[locale]
  const checkedAt = component.latest
    ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(component.latest.timestamp))
    : '—'
  const duration = resultDurationMs(component.latest)
  return `${toneLabel(component.tone)} · ${t.latestCheck}: ${checkedAt} · ${t.responseTime}: ${duration === null ? '—' : `${duration}ms`}`
}

function componentMarkup(component: ComponentStatus, nested = false, index = 0): string {
  return `<article class="component${nested ? ' nested' : ''}" style="--component-index: ${Math.min(index, 9)}">
    <div class="component-row">
      <div class="component-title">
        ${statusDot(component.tone)}
        <span class="component-title-text">${escapeHtml(component.name)}</span>
        <button class="info-button" type="button" data-component-info="${escapeHtml(component.key)}" aria-label="View description">${icon('info')}</button>
      </div>
      <span class="uptime-label">${escapeHtml(formatUptime(component.uptime))}</span>
    </div>
    ${renderBars(buildBars(component.results), componentDescription(component))}
  </article>`
}

function renderCalendar(): string {
  const year = selectedMonth.getFullYear()
  const month = selectedMonth.getMonth()
  const firstDay = new Date(year, month, 1)
  const mondayOffset = (firstDay.getDay() + 6) % 7
  const gridStart = new Date(year, month, 1 - mondayOffset)
  const today = new Date()
  const eventDays = new Set(events.filter((event) => event.timestamp.getFullYear() === year && event.timestamp.getMonth() === month).map((event) => event.timestamp.getDate()))
  const weekdays = locale === 'zh-CN' ? ['一', '二', '三', '四', '五', '六', '日'] : ['M', 'T', 'W', 'T', 'F', 'S', 'S']
  const days = Array.from({ length: 42 }, (_, index) => {
    const date = new Date(gridStart)
    date.setDate(gridStart.getDate() + index)
    const outside = date.getMonth() !== month
    const isToday = date.toDateString() === today.toDateString()
    const hasEvent = !outside && eventDays.has(date.getDate())
    const classes = `calendar-day${outside ? ' outside' : ''}${isToday ? ' today' : ''}${hasEvent ? ' has-event' : ''}`
    const label = new Intl.DateTimeFormat(locale, { dateStyle: 'full' }).format(date)
    if (hasEvent) {
      return `<button class="${classes}" type="button" data-event-day="${date.toISOString()}" aria-label="${escapeHtml(label)}"><span>${date.getDate()}</span></button>`
    }
    return `<div class="${classes}"><span>${date.getDate()}</span></div>`
  }).join('')
  return `<div class="weekdays">${weekdays.map((day) => `<span>${day}</span>`).join('')}</div><div class="calendar-grid">${days}</div>`
}

interface TransientState {
  popovers: string[]
  groupExpanded: boolean
  modal: { title: string; description: string; events: StatusEvent[] } | null
}

function captureTransientState(): TransientState {
  return {
    popovers: ['language-popover', 'theme-popover'].filter(
      (id) => document.querySelector<HTMLElement>(`#${id}`)?.hidden === false,
    ),
    groupExpanded: document.querySelector<HTMLElement>('.component-group')?.dataset.expanded === 'true',
    modal: openModal,
  }
}

function restoreTransientState(state: TransientState): void {
  for (const id of state.popovers) {
    const popover = document.querySelector<HTMLElement>(`#${id}`)
    const button = document.querySelector<HTMLElement>(`#${id.replace('-popover', '-button')}`)
    if (popover && button) {
      popover.hidden = false
      positionPopover(popover, button)
    }
  }
  if (state.groupExpanded) {
    document.querySelector('.component-group')?.setAttribute('data-expanded', 'true')
    document.querySelector('.component-group-toggle')?.setAttribute('aria-expanded', 'true')
  }
  if (state.modal) {
    showModal(state.modal.title, state.modal.description, state.modal.events)
  }
}

function render(preserveInteractions = false): void {
  const transient = preserveInteractions ? captureTransientState() : null
  const entering = !hasPainted
  const t = translations[locale]
  const tone = overallTone(components)
  const copy = statusCopy(tone)
  const primary = components.filter((component) => primaryNames.has(component.name))
  const infrastructure = components.filter((component) => !primaryNames.has(component.name))
  const groupUptime = infrastructure.length && infrastructure.every((component) => component.uptime !== null)
    ? infrastructure.reduce((total, component) => total + (component.uptime ?? 0), 0) / infrastructure.length
    : null
  const groupTone = infrastructure.length ? overallTone(infrastructure) : 'unknown'

  root!.innerHTML = `<div class="status-shell${entering ? ' is-entering' : ''}">
    <header class="status-header">
      <a class="brand" href="/" aria-label="OpenScience"><img src="/openscience-mark.svg" alt=""><span>OpenScience</span></a>
      <div class="header-actions">
        <button class="button subscribe-button" type="button" data-open-modal="subscribe">${icon('bell')}<span class="subscribe-label">${t.subscribe}</span></button>
        <button class="button icon-button" type="button" id="language-button" aria-label="${t.language}" title="${t.language}">${icon('language')}</button>
        <button class="button icon-button" type="button" id="theme-button" aria-label="${t.theme}" title="${t.theme}">${icon('sun')}</button>
      </div>
    </header>
    <main class="status-main">
      <div class="stack">
        <section class="summary ${tone}">
          <div class="summary-row">${statusDot(tone)}<span>${copy.title}</span></div>
          <p>${copy.body}</p>
        </section>
        <section class="system-panel">
          <div class="panel-heading"><h2>${t.systemStatus}</h2><div class="panel-meta"><span class="live-indicator"><span class="live-dot" aria-hidden="true"></span>${t.live}</span><span class="period-label">${t.uptimeWindow}</span></div></div>
          <div class="component-list">
            ${primary.map((component, index) => componentMarkup(component, false, index)).join('')}
            ${infrastructure.length ? `<article class="component component-group" data-expanded="false">
              <button class="component-group-toggle" type="button" aria-expanded="false">
                <div class="component-row"><div class="group-title-row">${statusDot(groupTone)}<span class="component-title-text">${t.infrastructure}</span><span class="component-count">${infrastructure.length} ${t.components}</span>${icon('down').replace('<svg ', '<svg class="group-chevron" ')}</div><span class="uptime-label">${formatUptime(groupUptime)}</span></div>
                ${renderBars(aggregateBars(infrastructure), `${t.infrastructure}: ${toneLabel(groupTone)}`)}
              </button>
              <div class="group-children"><div class="group-children-inner">${infrastructure.map((component, index) => componentMarkup(component, true, index)).join('')}</div></div>
            </article>` : ''}
          </div>
        </section>
        <section class="calendar-section">
          <div class="calendar-panel"><div class="calendar-heading"><h2>${t.eventCalendar}</h2><div class="period-control"><button class="chevron-button" id="previous-month" type="button" aria-label="Previous month">${icon('left')}</button><span>${monthLabel(selectedMonth, locale)}</span><button class="chevron-button" id="next-month" type="button" aria-label="Next month" ${selectedMonth.getFullYear() === new Date().getFullYear() && selectedMonth.getMonth() === new Date().getMonth() ? 'disabled' : ''}>${icon('right')}</button></div></div><div class="calendar">${renderCalendar()}</div></div>
          <button class="button history-button" type="button" data-open-modal="history">${icon('calendar')}${t.historicalEvents}</button>
        </section>
      </div>
    </main>
    <footer class="status-footer" aria-hidden="true"></footer>
  </div>
  <div class="popover" id="language-popover" hidden><button type="button" data-locale="en" aria-current="${locale === 'en'}">English</button><button type="button" data-locale="zh-CN" aria-current="${locale === 'zh-CN'}">简体中文</button></div>
  <div class="popover" id="theme-popover" hidden><button type="button" data-theme="system" aria-current="${theme === 'system'}">System</button><button type="button" data-theme="light" aria-current="${theme === 'light'}">Light</button><button type="button" data-theme="dark" aria-current="${theme === 'dark'}">Dark</button></div>
  <div class="modal-backdrop" id="modal-backdrop" hidden><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-header"><div><h2 id="modal-title"></h2><p id="modal-description"></p></div><button class="modal-close" type="button" aria-label="${t.close}">${icon('close')}</button></div><div class="event-list" id="modal-content"></div></section></div>`
  hasPainted = true
  if (transient) restoreTransientState(transient)
  bindInteractions()
}

function positionPopover(popover: HTMLElement, trigger: HTMLElement): void {
  const rect = trigger.getBoundingClientRect()
  popover.style.top = `${rect.bottom + 6}px`
  popover.style.left = `${Math.max(8, rect.right - popover.offsetWidth)}px`
}

function showModal(title: string, description: string, modalEvents: StatusEvent[] = []): void {
  openModal = { title, description, events: modalEvents }
  const backdrop = document.querySelector<HTMLElement>('#modal-backdrop')
  const titleNode = document.querySelector<HTMLElement>('#modal-title')
  const descriptionNode = document.querySelector<HTMLElement>('#modal-description')
  const content = document.querySelector<HTMLElement>('#modal-content')
  if (!backdrop || !titleNode || !descriptionNode || !content) return
  titleNode.textContent = title
  descriptionNode.textContent = description
  content.innerHTML = modalEvents.length
    ? modalEvents.slice(0, 100).map((event) => `<div class="event-item"><span>${statusDot(event.type === 'HEALTHY' ? 'healthy' : 'outage')} ${escapeHtml(event.component)} · ${event.type === 'HEALTHY' ? toneLabel('healthy') : toneLabel('outage')}</span><time>${new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(event.timestamp)}</time></div>`).join('')
    : ''
  backdrop.hidden = false
  document.body.style.overflow = 'hidden'
}

function closeModal(): void {
  openModal = null
  const backdrop = document.querySelector<HTMLElement>('#modal-backdrop')
  if (backdrop) backdrop.hidden = true
  document.body.style.overflow = ''
}

function bindInteractions(): void {
  document.querySelector('.component-group-toggle')?.addEventListener('click', (event) => {
    const button = event.currentTarget as HTMLButtonElement
    const group = button.closest<HTMLElement>('.component-group')
    if (!group) return
    const expanded = group.dataset.expanded !== 'true'
    group.dataset.expanded = String(expanded)
    button.setAttribute('aria-expanded', String(expanded))
  })

  const bindPopover = (buttonId: string, popoverId: string) => {
    const button = document.querySelector<HTMLElement>(`#${buttonId}`)
    const popover = document.querySelector<HTMLElement>(`#${popoverId}`)
    button?.addEventListener('click', () => {
      if (!popover) return
      popover.hidden = !popover.hidden
      if (!popover.hidden) positionPopover(popover, button)
    })
  }
  bindPopover('language-button', 'language-popover')
  bindPopover('theme-button', 'theme-popover')

  document.querySelectorAll<HTMLButtonElement>('#language-popover [data-locale]').forEach((button) => button.addEventListener('click', () => {
    locale = parseStatusLocale(button.dataset.locale)
    localStorage.setItem('openscience-status-locale', locale)
    document.documentElement.lang = locale
    render()
  }))
  document.querySelectorAll<HTMLButtonElement>('#theme-popover [data-theme]').forEach((button) => button.addEventListener('click', () => {
    theme = parseStatusTheme(button.dataset.theme)
    localStorage.setItem('openscience-status-theme', theme)
    applyTheme()
    render()
  }))

  document.querySelector('#previous-month')?.addEventListener('click', () => {
    selectedMonth = new Date(selectedMonth.getFullYear(), selectedMonth.getMonth() - 1, 1)
    render()
  })
  document.querySelector('#next-month')?.addEventListener('click', () => {
    selectedMonth = new Date(selectedMonth.getFullYear(), selectedMonth.getMonth() + 1, 1)
    render()
  })

  document.querySelectorAll<HTMLElement>('[data-open-modal]').forEach((button) => button.addEventListener('click', () => {
    const t = translations[locale]
    if (button.dataset.openModal === 'subscribe') {
      showModal(t.subscribeTitle, t.subscribeBody)
    } else {
      showModal(t.historyTitle, events.length ? '' : t.noEvents, events)
    }
  }))
  document.querySelectorAll<HTMLElement>('[data-component-info]').forEach((button) => button.addEventListener('click', () => {
    const component = components.find((item) => item.key === button.dataset.componentInfo)
    if (component) showModal(component.name, componentDescription(component))
  }))
  document.querySelectorAll<HTMLElement>('[data-event-day]').forEach((day) => {
    const openDay = () => {
      const date = new Date(day.dataset.eventDay ?? '')
      const dayEvents = events.filter((event) => event.timestamp.toDateString() === date.toDateString())
      showModal(new Intl.DateTimeFormat(locale, { dateStyle: 'full' }).format(date), '', dayEvents)
    }
    day.addEventListener('click', openDay)
  })
  document.querySelector('.modal-close')?.addEventListener('click', closeModal)
  document.querySelector('#modal-backdrop')?.addEventListener('click', (event) => { if (event.target === event.currentTarget) closeModal() })
}

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && openModal) closeModal()
})

async function fetchText(url: string): Promise<string> {
  const response = await fetch(url, { headers: { Accept: 'text/plain' } })
  if (!response.ok) throw new Error(`${url} returned ${response.status}`)
  return response.text()
}

async function loadStatus(): Promise<void> {
  try {
    const response = await fetch('/uptime/api/v1/endpoints/statuses?page=1&pageSize=90', { headers: { Accept: 'application/json' } })
    if (!response.ok) throw new Error(`Gatus returned ${response.status}`)
    const listed = (await response.json()) as GatusEndpoint[]
    const production = listed.filter((endpoint) => endpoint.group === 'Production')
    components = await Promise.all(production.map(async (endpoint) => {
      const [detailsResponse, uptimeResponse] = await Promise.all([
        fetch(`/uptime/api/v1/endpoints/${encodeURIComponent(endpoint.key)}/statuses?page=1&pageSize=90`, { headers: { Accept: 'application/json' } }),
        fetchText(`/uptime/api/v1/endpoints/${encodeURIComponent(endpoint.key)}/uptimes/30d`),
      ])
      const details = detailsResponse.ok ? await detailsResponse.json() as GatusEndpoint : endpoint
      const latest = newestResult(details.results ?? endpoint.results ?? [])
      return {
        ...endpoint,
        ...details,
        results: details.results ?? endpoint.results ?? [],
        uptime: parseUptime(uptimeResponse),
        latest,
        tone: resultTone(latest),
      }
    }))
    events = collectEvents(components)
  } catch (error) {
    console.error('Unable to load Gatus status data', error)
    components = []
    events = []
  }
  render(true)
}

applyTheme()
document.documentElement.lang = locale
render()
void loadStatus()
const refreshTimer = window.setInterval(() => void loadStatus(), 30_000)
window.addEventListener('beforeunload', () => window.clearInterval(refreshTimer))
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (theme === 'system') applyTheme() })
