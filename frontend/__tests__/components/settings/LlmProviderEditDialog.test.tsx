import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LlmProviderEditDialog } from '../../../src/pages/settings/LlmProviderEditDialog';
import { renderWithProviders } from '../../../src/test/render';

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
});
