// error-code messages — English
const errors = {
    // Permissions
    project_editor_required: 'Project editor permission is required.',
    project_owner_required: 'Only the project owner can perform this action.',
    project_publish_required: 'Project publish permission is required.',
    workspace_owner_required: 'Workspace owner permission is required.',
    task_owner_required: 'Only the task owner can perform this action.',
    environment_admin_required: 'Only administrators can manage environments.',
    environment_grant_required: 'You need an execution grant for this environment.',
    auth_user_required: 'A registered account is required for this operation.',

    // Not found
    domain_resource_not_found: 'The requested resource was not found.',

    // Idempotency
    idempotency_key_required: 'An Idempotency-Key header is required for this action.',
    idempotency_key_too_long: 'The Idempotency-Key header is too long.',
    idempotency_key_conflict: 'This Idempotency-Key was already used for a different request.',
    idempotency_response_invalid: 'The stored response for this Idempotency-Key is invalid.',

    // Projects and members
    project_create_failed: 'The project could not be created. Please retry.',
    project_default_conflict: 'The default project conflicts with existing state.',
    project_default_create_failed: 'The default project could not be created. Please retry.',
    project_default_provisioning_incomplete:
        'Default project provisioning is incomplete. Contact an administrator.',
    project_default_archived:
        'The default project is archived and needs explicit reconciliation. Contact an administrator.',
    project_default_archive_forbidden: 'The default project cannot be archived.',
    project_default_transfer_forbidden: 'The default project ownership cannot be transferred.',
    project_already_archived: 'This project is already archived.',
    project_not_archived: 'This project is not archived.',
    member_role_invalid: 'Unknown member role.',
    member_publish_role_invalid: 'Only editors can be granted publish permission.',
    member_owner_missing: 'The project owner must remain a project member.',
    member_owner_immutable: 'The project owner cannot be removed as a member.',
    task_relationship_create_failed: 'The task relationship could not be created.',
    project_transfer_owner_required: 'A new owner is required to transfer this project.',

    // Environments
    environment_create_failed: 'The environment could not be created. Please retry.',
    environment_alias_exists: 'An environment with this alias already exists.',
    environment_referenced_repoint:
        'This environment is referenced by existing work and cannot be repointed to a different endpoint.',
    environment_capacity_exhausted:
        'This environment has reached its concurrent task limit. Wait for running tasks to finish.',

    // Workspaces
    workspace_create_failed: 'The workspace could not be created. Please retry.',
    workspace_environment_required: 'The workspace requires an active environment.',
    workspace_path_already_registered: 'This workspace path is already registered.',
    workspace_link_project_inactive: 'Linking requires an active project.',
    workspace_link_workspace_inactive: 'Linking requires an active workspace.',
    workspace_link_environment_inactive: 'Linking requires an active environment.',
    workspace_primary_compare_failed:
        'The workspace changed while you were editing. Refresh and retry.',
    workspace_primary_detach_requires_replacement:
        'Detaching the primary workspace requires a replacement workspace.',
    workspace_primary_replacement_required:
        'Replace the primary workspace before unregistering this one.',
    workspace_primary_replace_required:
        'Use the replace operation to change the primary workspace.',
    workspace_primary_not_linked: 'The primary workspace must already be an active project link.',
    workspace_unregister_tasks_pending:
        'This workspace still has queued or running tasks and cannot be unregistered.',

    // Project context
    context_candidate_source_required: 'A context candidate must reference its source task.',
    context_candidate_rejected: 'A rejected candidate cannot be accepted.',
    context_candidate_accepted: 'An accepted candidate cannot be rejected.',
    context_fragment_source_required: 'The context fragment needs a source type.',
    context_fragment_budget_invalid: 'The context fragment byte budget cannot be negative.',
    context_preview_expired: 'The context update preview has expired. Preview again and retry.',
    context_preview_already_confirmed: 'This context update preview was already confirmed.',
    context_draft_required: 'No context draft exists for this project yet.',
    context_snapshot_ref_invalid: 'The selected context snapshot is not valid for this task.',
    context_version_unreviewed:
        "This project's context was created before context tracking was added. Publish the project context again, then retry.",
    context_manifest_missing:
        "This project's saved context is damaged. Publish the project context again, then retry.",
    context_manifest_invalid:
        "This project's saved context is damaged. Publish the project context again, then retry.",

    // Tasks
    task_project_required: 'A project is required to create a task.',
    task_workspace_not_linked: 'The workspace must be linked to the project first.',
    task_workspace_environment_inactive:
        'The workspace and its environment must be active to run tasks.',
    task_environment_mismatch:
        'The environment no longer matches this workspace. Refresh and pick it again.',
    task_move_turn_active: 'Interrupt the active turn before moving this task.',
    task_move_same_project: 'This task already belongs to the target project.',
    task_execution_slot_held: 'This task already holds an execution slot.',
    engine_tenant_ineligible:
      'The selected engine is not available in this deployment. Choose another engine.',
    fork_transfer_range_invalid: 'The fork transfer range is invalid.',

    // Conversation contract errors
    active_turn_exists: 'This task already has an active turn. Wait for it to finish.',
    expected_turn_mismatch: 'The turn changed while you were working. Refresh and retry.',
    turn_not_active: 'This turn is no longer active.',
    delivery_unknown: 'The delivery state of this turn is unknown. Refresh to check again.',
    runtime_lost: 'The runtime connection was lost. Retry or resume the task.',
    session_unavailable: 'The engine session is unavailable. Retry shortly.',
    capability_unsupported: 'The current engine does not support this capability.',
    task_not_open: 'This task is not open. Reopen it to continue.',
    fork_confirmation_required: 'Confirm the fork preview before forking.',
    migration_required: 'This task requires a migration before the action. Contact support.',
    invalid_state_transition: 'This action is not valid in the current state. Refresh and retry.',
    provider_contract_mismatch: 'The engine returned an unexpected response. Retry the action.',
};

export default errors;
