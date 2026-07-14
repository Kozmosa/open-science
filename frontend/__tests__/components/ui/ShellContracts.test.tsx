import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CardGrid, PageShell } from '@design-system';
import { getRouteDefinition, getVisibleRoutes, ROUTE_REGISTRY } from '@/app/routeRegistry';
import { LocaleProvider } from '@/shared/i18n';

describe('osci shell contracts', () => {
  it('uses one route registry for titles, navigation, commands, and admin filtering', () => {
    expect(new Set(ROUTE_REGISTRY.map((route) => route.path)).size).toBe(ROUTE_REGISTRY.length);
    expect(getRouteDefinition('/tasks')?.titleKey).toBe('navigation.tasks.label');
    expect(getVisibleRoutes(false, true).some((route) => route.id === 'sessions')).toBe(false);
    expect(getVisibleRoutes(true, true).some((route) => route.id === 'sessions')).toBe(true);
    expect(getVisibleRoutes(true, true).some((route) => route.id === 'workspace-browser')).toBe(false);
    expect(getVisibleRoutes(true, false).some((route) => route.id === 'workspace-browser')).toBe(true);
    expect(getRouteDefinition('/literature')?.keywords).toContain('papers');
  });

  it('keeps PageShell legacy by default and exposes an explicit canvas variant', () => {
    const { rerender } = render(<PageShell>Legacy</PageShell>);
    expect(screen.getByText('Legacy')).toHaveAttribute('data-page-shell-variant', 'legacy');

    rerender(<PageShell variant="canvas">Canvas</PageShell>);
    expect(screen.getByText('Canvas')).toHaveAttribute('data-page-shell-variant', 'canvas');
  });

  it('pins attention cards first and removes their drag handle', () => {
    render(
      <LocaleProvider initialLocale="en">
        <CardGrid
          groups={[{ id: 'overview', cards: [
            { id: 'progress', kind: 'progress' },
            { id: 'attention', kind: 'attention' },
          ] }]}
          cardOrder={['progress']}
          onCardOrderChange={() => undefined}
          renderCard={(_id, kind) => <article>{kind}</article>}
        />
      </LocaleProvider>,
    );

    const grid = screen.getByText('attention').parentElement?.parentElement;
    expect(grid).not.toBeNull();
    expect(within(grid as HTMLElement).getAllByRole('article').map((item) => item.textContent)).toEqual(['attention', 'progress']);
    expect(screen.getAllByRole('button', { name: 'Drag to reorder' })).toHaveLength(1);
  });
});
