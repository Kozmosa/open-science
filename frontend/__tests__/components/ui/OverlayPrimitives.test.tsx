import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState, type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  Dialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  ToastProvider,
  useToast,
} from '@design-system';
import { LocaleProvider } from '@/shared/i18n';

function renderLocalized(ui: ReactNode) {
  return render(<LocaleProvider initialLocale="en">{ui}</LocaleProvider>);
}

describe('osci overlay primitives', () => {
  it('closes Dialog with Escape and restores focus to the opener', async () => {
    const user = userEvent.setup();

    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Open settings</button>
          <Dialog isOpen={open} onClose={() => setOpen(false)} title="Settings">
            <button type="button">Save settings</button>
          </Dialog>
        </>
      );
    }

    renderLocalized(<Harness />);
    const opener = screen.getByRole('button', { name: 'Open settings' });
    await user.click(opener);

    expect(screen.getByRole('dialog', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Save settings' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });

  it('gives titleless dialogs an explicit accessible name', () => {
    renderLocalized(
      <Dialog isOpen onClose={vi.fn()} ariaLabel="Archive task confirmation" showCloseButton={false}>
        Confirm archive
      </Dialog>,
    );

    expect(screen.getByRole('dialog', { name: 'Archive task confirmation' })).toBeInTheDocument();
  });

  it('supports keyboard selection in DropdownMenu', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Open actions</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>Rename</DropdownMenuItem>
          <DropdownMenuItem onSelect={onSelect}>Archive</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );

    screen.getByRole('button', { name: 'Open actions' }).focus();
    await user.keyboard('{Enter}{ArrowDown}{Enter}');
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it('preserves the showToast(message, type) adapter contract', async () => {
    const user = userEvent.setup();
    function ToastHarness() {
      const { showToast } = useToast();
      return <button type="button" onClick={() => showToast('Saved', 'success')}>Save</button>;
    }

    renderLocalized(
      <ToastProvider>
        <ToastHarness />
      </ToastProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByText('Saved')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
  });
});
