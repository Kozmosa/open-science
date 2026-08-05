import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LiteraturePage from '../../src/pages/LiteraturePage';
import { renderWithProviders } from '@/test-support/render';
import {
  createLiteratureCheck,
  getLiteratureOverview,
  getLiteraturePaper,
  getLiteratureResearchTasks,
  getLiteratureSummary,
  updateLiteraturePaperState,
} from '@features/literature/api';

vi.mock('@features/literature/api', () => ({
  createLiteratureCheck: vi.fn(() => Promise.resolve({ check_id: 'check-1', status: 'planned' })),
  getLiteratureOverview: vi.fn(() => Promise.resolve({
    last_successful_check_at: null,
    next_scheduled_check_at: null,
    active_check: null,
    counts: { today: 0, unread: 0, saved: 0, updated: 0 },
  })),
  getLiteraturePapers: vi.fn(() => Promise.resolve({ items: [], next_cursor: null, total: 0 })),
  getLiteratureTopics: vi.fn(() => Promise.resolve({ items: [] })),
  getLiteraturePaper: vi.fn(),
  getLiteratureSummary: vi.fn(),
  getLiteratureResearchTasks: vi.fn(),
  createLiteratureResearchTask: vi.fn(),
  requestLiteratureSummary: vi.fn(),
  updateLiteraturePaperState: vi.fn(),
}));

const paperDetail = {
  paper_id: 'paper-1',
  provider: 'arxiv',
  external_id: '2607.00001',
  title: 'Inspectable research paper',
  authors: ['Ada Researcher'],
  abstract: 'A paper abstract.',
  primary_category: 'cs.AI',
  categories: ['cs.AI'],
  published_at: '2026-07-14T08:00:00Z',
  updated_at: '2026-07-15T08:00:00Z',
  source_url: 'https://arxiv.org/abs/2607.00001',
  pdf_url: 'https://arxiv.org/pdf/2607.00001',
  current_version_id: 'version-1',
  matched_topics: [],
  user_state: {
    is_read: false,
    is_saved: true,
    is_ignored: true,
    first_seen_at: '2026-07-14T08:00:00Z',
    last_seen_at: '2026-07-15T08:00:00Z',
    latest_seen_version_id: 'version-1',
  },
  versions: [{
    version_id: 'version-1',
    provider_version: 'v1',
    published_at: '2026-07-14T08:00:00Z',
    updated_at: '2026-07-15T08:00:00Z',
    first_seen_at: '2026-07-14T08:00:00Z',
  }],
};

describe('LiteraturePage', () => {
  beforeEach(() => {
    vi.mocked(getLiteratureOverview).mockResolvedValue({
      last_successful_check_at: null,
      next_scheduled_check_at: null,
      active_check: null,
      counts: { today: 0, unread: 0, saved: 0, updated: 0 },
    });
  });

  it('renders the canvas inbox with a single source-check action and persistent URL filters', async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<LiteraturePage />, { route: '/literature' });

    expect(await screen.findByRole('heading', { name: "Today's literature inbox" })).toBeInTheDocument();
    expect(screen.getByText('LITERATURE')).toBeInTheDocument();
    expect(screen.queryByText('Review newly matched papers first. Source checks and summaries run in the background.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check latest literature' })).toBeInTheDocument();
    expect(container.firstElementChild).toHaveAttribute('data-page-shell-variant', 'canvas');
    expect(screen.getByTestId('literature-controls')).toBeInTheDocument();
    expect(screen.getByTestId('literature-check-status')).toHaveTextContent('Last successful check');
    expect(screen.getByTestId('literature-check-status')).toHaveTextContent('Next planned check');
    expect(screen.getByRole('combobox', { name: 'Filter by topic' })).toHaveTextContent('All topics');
    expect(screen.getByRole('combobox', { name: 'Filter by category' })).toHaveTextContent('All categories');
    expect(screen.getByRole('button', { name: 'Unread' })).toBeInTheDocument();
    expect(screen.queryByText('My Subscriptions')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Check latest literature' }));
    expect(vi.mocked(createLiteratureCheck)).toHaveBeenCalledWith(
      expect.stringMatching(/^literature\.check\.create:/),
    );
  });

  it('keeps the literature eyebrow in English while localizing the compact controls', async () => {
    vi.mocked(getLiteratureOverview).mockResolvedValue({
      last_successful_check_at: null,
      next_scheduled_check_at: null,
      active_check: {
        check_id: 'check-active',
        status: 'checking',
        trigger: 'manual',
        window_start: null,
        window_end: null,
        created_at: '2026-07-14T08:00:00Z',
        started_at: '2026-07-14T08:00:00Z',
        completed_at: null,
        next_attempt_at: null,
        error: null,
      },
      counts: { today: 1, unread: 5, saved: 2, updated: 0 },
    });

    renderWithProviders(<LiteraturePage />, {
      route: '/literature?view=unread',
      locale: 'zh',
    });

    expect(await screen.findByRole('heading', { name: '今日文献收件箱' })).toBeInTheDocument();
    expect(screen.getByText('LITERATURE')).toBeInTheDocument();
    expect(screen.queryByText('先阅读今日匹配到的新论文；来源检查和摘要会在后台完成。')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '检查最新文献' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '收件箱' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '未读' })).toBeInTheDocument();
    expect(await screen.findByText('正在检查来源')).toBeInTheDocument();
    expect(screen.getByTestId('literature-check-status')).toHaveTextContent('上次成功检查');
    expect(screen.getByTestId('literature-check-status')).toHaveTextContent('下次计划检查');
    expect(screen.getByTestId('literature-check-status')).toHaveTextContent('正在检查来源');
    expect(screen.getByTestId('literature-check-status')).not.toHaveTextContent('checking');
    expect(screen.getByTestId('literature-check-status')).not.toHaveTextContent('Last check');
    expect(screen.getByTestId('literature-check-status')).not.toHaveTextContent('Next check');
    expect(screen.getByRole('combobox', { name: '按关注方向筛选' })).toHaveTextContent('全部方向');
    expect(screen.getByRole('combobox', { name: '按分类筛选' })).toHaveTextContent('全部分类');
  });

  it('shows and updates user state in the paper detail drawer', async () => {
    const user = userEvent.setup();
    vi.mocked(getLiteraturePaper).mockResolvedValue(paperDetail);
    vi.mocked(getLiteratureSummary).mockResolvedValue({ status: 'not_requested' });
    vi.mocked(getLiteratureResearchTasks).mockResolvedValue({ items: [] });
    vi.mocked(updateLiteraturePaperState).mockResolvedValue(undefined as never);

    renderWithProviders(<LiteraturePage />, { route: '/literature?paper=paper-1' });

    expect(await screen.findByRole('heading', { name: 'Your status' })).toBeInTheDocument();
    const drawer = screen.getByRole('dialog');
    expect(within(drawer).getByText('Unread')).toBeInTheDocument();
    expect(within(drawer).getByText('Saved')).toBeInTheDocument();
    expect(within(drawer).getByText('Ignored')).toBeInTheDocument();
    expect(screen.getByTestId('literature-paper-detail-content')).toHaveClass('p-4', 'sm:p-5');
    expect(within(drawer).getByRole('heading', { name: 'Versions' })).toBeInTheDocument();
    expect(within(drawer).getByRole('heading', { name: 'Summary' })).toBeInTheDocument();
    expect(within(drawer).getByRole('heading', { name: 'Research tasks' })).toBeInTheDocument();
    expect(within(drawer).getByRole('link', { name: 'Source' })).toHaveAttribute(
      'href',
      'https://arxiv.org/abs/2607.00001',
    );
    expect(within(drawer).getByRole('button', { name: 'Convert to Task' })).toHaveClass('w-full');
    expect(within(drawer).getByText('No research tasks have been created from this paper yet.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Restore to inbox' }));
    expect(vi.mocked(updateLiteraturePaperState)).toHaveBeenCalledWith(
      'paper-1',
      { is_ignored: false },
      expect.stringMatching(/^literature\.paper\.state:/),
    );
  });

  it('localizes the redesigned paper detail hierarchy in Chinese', async () => {
    vi.mocked(getLiteraturePaper).mockResolvedValue(paperDetail);
    vi.mocked(getLiteratureSummary).mockResolvedValue({ status: 'not_requested' });
    vi.mocked(getLiteratureResearchTasks).mockResolvedValue({ items: [] });

    renderWithProviders(<LiteraturePage />, {
      route: '/literature?paper=paper-1',
      locale: 'zh',
    });

    const drawer = await screen.findByRole('dialog', { name: 'Inspectable research paper' });
    expect(within(drawer).getByRole('button', { name: '关闭' })).toBeInTheDocument();
    expect(within(drawer).getByRole('heading', { name: '版本记录' })).toBeInTheDocument();
    expect(within(drawer).getByRole('heading', { name: '摘要' })).toBeInTheDocument();
    expect(within(drawer).getByRole('heading', { name: '研究任务' })).toBeInTheDocument();
    expect(within(drawer).getByRole('link', { name: '原文' })).toBeInTheDocument();
    expect(within(drawer).getByRole('button', { name: '生成摘要' })).toBeInTheDocument();
    expect(within(drawer).getByRole('button', { name: '转换为任务' })).toBeInTheDocument();
    expect(within(drawer).getByText('尚未基于这篇论文创建研究任务。')).toBeInTheDocument();
  });
});
