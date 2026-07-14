import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Plus } from 'lucide-react';
import { Button } from '@design-system';

describe('Button', () => {
  it('renders as an inline-flex container so gap works for icon + label', () => {
    render(
      <Button className="gap-1.5">
        <Plus size={14} data-testid="icon" />
        <span>New Task</span>
      </Button>
    );

    const button = screen.getByRole('button');
    expect(button).toHaveClass('inline-flex');
    expect(button).toHaveClass('items-center');
    expect(button).toHaveClass('justify-center');
    expect(button).toHaveClass('gap-1.5');
    expect(screen.getByTestId('icon')).toBeInTheDocument();
    expect(screen.getByText('New Task')).toBeInTheDocument();
  });

  it('allows consumer className to override base padding and text size', () => {
    render(<Button className="px-3 text-xs">Label</Button>);
    const button = screen.getByRole('button');
    // Consumer className comes last, so Tailwind later-wins applies
    expect(button).toHaveClass('px-3');
    expect(button).toHaveClass('text-xs');
  });

  it('uses semantic danger tokens instead of fixed red palette classes', () => {
    render(<Button variant="danger">Delete</Button>);

    expect(screen.getByRole('button', { name: 'Delete' })).toHaveClass(
      'bg-[var(--osci-color-danger)]',
      'text-[var(--osci-color-on-accent)]',
      'hover:opacity-90'
    );
  });

  it('keeps loading content in layout while exposing busy state', () => {
    render(<Button isLoading>Save changes</Button>);

    const button = screen.getByRole('button', { name: /save changes/i });
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(button).toBeDisabled();
    expect(screen.getByText('Save changes')).toHaveClass('invisible');
  });

  it('supports an accessible icon-only size', () => {
    render(<Button size="icon" aria-label="Create task"><Plus aria-hidden="true" /></Button>);

    expect(screen.getByRole('button', { name: 'Create task' })).toHaveClass('h-10', 'w-10', 'p-0');
  });
});
