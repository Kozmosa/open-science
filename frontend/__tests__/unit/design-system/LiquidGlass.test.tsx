import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LiquidGlass, MotionPreferenceProvider } from '@design-system';

describe('LiquidGlass', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('enables enhanced material when motion and browser capabilities allow it', async () => {
    vi.stubGlobal('CSS', { supports: () => true });

    render(
      <MotionPreferenceProvider motionEnabled>
        <LiquidGlass data-testid="glass">Content</LiquidGlass>
      </MotionPreferenceProvider>,
    );

    expect(await screen.findByTestId('glass')).toHaveAttribute('data-enhanced', 'true');
  });

  it('keeps only the base material when motion is disabled', () => {
    vi.stubGlobal('CSS', { supports: () => true });

    render(
      <MotionPreferenceProvider motionEnabled={false}>
        <LiquidGlass data-testid="glass" interactive>Content</LiquidGlass>
      </MotionPreferenceProvider>,
    );

    expect(screen.getByTestId('glass')).toHaveAttribute('data-enhanced', 'false');
    expect(screen.getByTestId('glass')).toHaveAttribute('data-interactive', 'false');
  });
});
