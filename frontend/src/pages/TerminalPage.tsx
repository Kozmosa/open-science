import { EnvironmentSelectorPanel, TerminalBenchCard, useEnvironmentSelection } from '../components';

function TerminalPage() {
  const environmentSelection = useEnvironmentSelection();

  return (
    <div className="px-4 py-8 sm:px-6 lg:px-8">
      <section className="mb-8 space-y-3">
        <p className="text-sm font-medium uppercase tracking-wide text-[var(--accent)]">
          Terminal
        </p>
        <h1 className="text-3xl font-semibold text-gray-900">Personal terminal bench</h1>
        <p className="max-w-3xl text-sm text-gray-600 sm:text-base">
          This route is dedicated to the personal terminal bench. Task Harness v1 keeps task output
          in the Tasks page instead of attaching task windows here.
        </p>
      </section>

      <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <EnvironmentSelectorPanel {...environmentSelection} />
        <TerminalBenchCard selectedEnvironment={environmentSelection.selectedEnvironment} />
      </section>
    </div>
  );
}

export default TerminalPage;
