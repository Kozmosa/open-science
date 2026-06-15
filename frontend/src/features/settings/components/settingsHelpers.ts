import type { EnvironmentTaskDefaults } from '@features/settings';

export function hasEnvironmentDefaultChanges(
  left: EnvironmentTaskDefaults,
  right: EnvironmentTaskDefaults
): boolean {
  return (
    left.titleTemplate !== right.titleTemplate ||
    left.taskInputTemplate !== right.taskInputTemplate ||
    left.researchAgentProfileId !== right.researchAgentProfileId ||
    left.taskConfigurationId !== right.taskConfigurationId
  );
}
