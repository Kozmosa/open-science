import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Alert } from '@design-system/primitives';

describe('Alert', () => {
  it('uses semantic design tokens for error, warning, and success variants', () => {
    const { rerender } = render(<Alert variant="error">Error</Alert>);
    expect(screen.getByText('Error')).toHaveClass(
      'border-[var(--danger-border)]',
      'bg-[var(--danger-soft)]',
      'text-[var(--danger-foreground)]'
    );

    rerender(<Alert variant="warning">Warning</Alert>);
    expect(screen.getByText('Warning')).toHaveClass(
      'border-[var(--warning-border)]',
      'bg-[var(--warning-soft)]',
      'text-[var(--warning-foreground)]'
    );

    rerender(<Alert variant="success">Success</Alert>);
    expect(screen.getByText('Success')).toHaveClass(
      'border-[var(--success-border)]',
      'bg-[var(--success-soft)]',
      'text-[var(--success-foreground)]'
    );
  });
});
