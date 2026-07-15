import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LlmProviderEditDialog } from '../../../src/pages/settings/LlmProviderEditDialog';
import { renderWithProviders } from '@/shared/test/render';

describe('LlmProviderEditDialog i18n', () => {
  it('uses localized placeholders and labels in Chinese', () => {
    renderWithProviders(
      <LlmProviderEditDialog provider={null} onSave={vi.fn()} onClose={vi.fn()} />,
      { locale: 'zh' }
    );

    expect(screen.getByPlaceholderText('例如 Kimi Coding')).toBeInTheDocument();
    expect(screen.getByLabelText('名称')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('e.g. Kimi Coding')).not.toBeInTheDocument();
  });

  it('uses the shared dialog contract and closes on Escape', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <LlmProviderEditDialog provider={null} onSave={vi.fn()} onClose={onClose} />,
      { locale: 'en' }
    );

    const dialog = screen.getByRole('dialog', { name: 'Add Provider' });
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });
});
