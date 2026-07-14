import type { TaskStatus } from '@/shared/types';
import { semanticToneClasses } from '@design-system';

export const statusClassName: Record<TaskStatus, string> = {
  queued: semanticToneClasses.muted,
  starting: semanticToneClasses.info,
  running: semanticToneClasses.success,
  succeeded: semanticToneClasses.success,
  failed: semanticToneClasses.danger,
  cancelled: semanticToneClasses.warning,
  paused: semanticToneClasses.info,
  launch_unknown: semanticToneClasses.warning,
  stopped_by_project_archive: semanticToneClasses.muted,
  stopped_permission_revoked: semanticToneClasses.danger,
  stopped_runtime_unknown: semanticToneClasses.warning,
};
