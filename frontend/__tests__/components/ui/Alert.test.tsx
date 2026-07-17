import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Alert } from '@design-system';

describe('Alert', () => {
  it('uses semantic design tokens for error, warning, and success variants', () => {
    const { rerender } = render(<Alert variant="error">Error</Alert>);
    expect(screen.getByText('Error')).toHaveClass(
      'border-[var(--osci-color-danger-border)]',
      'bg-[var(--osci-color-danger-soft)]',
      'text-[var(--osci-color-danger-foreground)]'
    );

    rerender(<Alert variant="warning">Warning</Alert>);
    expect(screen.getByText('Warning')).toHaveClass(
      'border-[var(--osci-color-warning-border)]',
      'bg-[var(--osci-color-warning-soft)]',
      'text-[var(--osci-color-warning-foreground)]'
    );

    rerender(<Alert variant="success">Success</Alert>);
    expect(screen.getByText('Success')).toHaveClass(
      'border-[var(--osci-color-success-border)]',
      'bg-[var(--osci-color-success-soft)]',
      'text-[var(--osci-color-success-foreground)]'
    );
  });
});
