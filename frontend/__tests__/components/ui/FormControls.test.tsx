import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  Checkbox,
  Form,
  FormField,
  Input,
  RadioGroup,
  RadioGroupItem,
  Skeleton,
  StatusBadge,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@design-system';

describe('osci form and state primitives', () => {
  it('supports keyboard toggling for checkbox and switch', async () => {
    const user = userEvent.setup();
    function Harness() {
      const [checked, setChecked] = useState(false);
      const [enabled, setEnabled] = useState(false);
      return (
        <>
          <label htmlFor="notify"><Checkbox id="notify" checked={checked} onCheckedChange={(value) => setChecked(value === true)} /> Notify</label>
          <label htmlFor="sync"><Switch id="sync" checked={enabled} onCheckedChange={setEnabled} /> Sync</label>
        </>
      );
    }

    render(<Harness />);
    const checkbox = screen.getByRole('checkbox', { name: 'Notify' });
    checkbox.focus();
    await user.keyboard(' ');
    expect(checkbox).toBeChecked();

    const toggle = screen.getByRole('switch', { name: 'Sync' });
    toggle.focus();
    await user.keyboard(' ');
    expect(toggle).toBeChecked();
  });

  it('supports keyboard selection in a radio group', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <RadioGroup onValueChange={onValueChange} aria-label="Mode">
        <label htmlFor="mode-first"><RadioGroupItem id="mode-first" value="first" /> First</label>
        <label htmlFor="mode-second"><RadioGroupItem id="mode-second" value="second" /> Second</label>
      </RadioGroup>,
    );

    await user.tab();
    await user.keyboard(' ');
    await waitFor(() => expect(screen.getByRole('radio', { name: 'First' })).toBeChecked());
    expect(onValueChange).toHaveBeenCalledWith('first');
  });

  it('connects form semantics and error announcements', () => {
    render(
      <Form aria-label="Profile form">
        <FormField label="Name" error="Name is required" required>
          <Input aria-label="Name" error="Name is required" />
        </FormField>
      </Form>,
    );

    expect(screen.getByRole('form', { name: 'Profile form' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('alert')).toHaveTextContent('Name is required');
  });

  it('exposes tab state and status badges while keeping skeleton decorative', async () => {
    const user = userEvent.setup();
    render(
      <>
        <Tabs defaultValue="overview">
          <TabsList aria-label="Project sections">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="tasks">Tasks</TabsTrigger>
          </TabsList>
          <TabsContent value="overview">Overview content</TabsContent>
          <TabsContent value="tasks">Task content</TabsContent>
        </Tabs>
        <StatusBadge tone="warning">Needs attention</StatusBadge>
        <Skeleton data-testid="skeleton" className="h-4" />
      </>,
    );

    await user.click(screen.getByRole('tab', { name: 'Tasks' }));
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Task content');
    expect(screen.getByText('Needs attention')).toHaveClass('bg-[var(--osci-color-warning-soft)]');
    expect(screen.getByTestId('skeleton')).toHaveAttribute('aria-hidden', 'true');
  });
});
