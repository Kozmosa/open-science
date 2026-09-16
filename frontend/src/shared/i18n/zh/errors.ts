// error-code messages — 简体中文
const errors = {
    // 权限
    project_editor_required: '需要项目编辑权限。',
    project_owner_required: '只有项目所有者可以执行此操作。',
    project_publish_required: '需要项目发布权限。',
    workspace_owner_required: '需要工作区所有者权限。',
    task_owner_required: '只有任务所有者可以执行此操作。',
    environment_admin_required: '只有管理员可以管理运行环境。',
    environment_grant_required: '你没有此运行环境的执行授权。',
    auth_user_required: '此操作需要一个已注册的账号。',

    // 未找到
    domain_resource_not_found: '未找到对应的资源。',

    // 幂等
    idempotency_key_required: '此操作需要提供 Idempotency-Key 请求头。',
    idempotency_key_too_long: 'Idempotency-Key 请求头过长。',
    idempotency_key_conflict: '这个 Idempotency-Key 已被用于其他请求。',
    idempotency_response_invalid: '这个 Idempotency-Key 对应的已存响应无效。',

    // 项目与成员
    project_create_failed: '项目创建失败,请重试。',
    project_default_conflict: '默认项目与现有状态冲突。',
    project_default_create_failed: '默认项目创建失败,请重试。',
    project_default_provisioning_incomplete: '默认项目初始化不完整,请联系管理员。',
    project_default_archived: '默认项目处于归档状态,需要显式处理,请联系管理员。',
    project_default_archive_forbidden: '默认项目不能被归档。',
    project_default_transfer_forbidden: '默认项目的所有权不能转让。',
    project_already_archived: '该项目已处于归档状态。',
    project_not_archived: '该项目未归档。',
    member_role_invalid: '未知的成员角色。',
    member_publish_role_invalid: '只有编辑者可以被授予发布权限。',
    member_owner_missing: '项目所有者必须是项目成员。',
    member_owner_immutable: '不能将项目所有者移出成员列表。',
    task_relationship_create_failed: '任务关系创建失败。',
    project_transfer_owner_required: '转让项目需要指定新的所有者。',

    // 运行环境
    environment_create_failed: '运行环境创建失败,请重试。',
    environment_alias_exists: '已存在同名别名的运行环境。',
    environment_referenced_repoint: '该运行环境已被引用,不能切换到不同的端点。',
    environment_capacity_exhausted: '该运行环境的并发任务数已达上限,请等待运行中的任务结束。',

    // 工作区
    workspace_create_failed: '工作区创建失败,请重试。',
    workspace_environment_required: '工作区需要一个处于活跃状态的运行环境。',
    workspace_path_already_registered: '该工作区路径已被注册。',
    workspace_link_project_inactive: '关联需要项目处于活跃状态。',
    workspace_link_workspace_inactive: '关联需要工作区处于活跃状态。',
    workspace_link_environment_inactive: '关联需要运行环境处于活跃状态。',
    workspace_primary_compare_failed: '工作区在你操作时发生了变化,请刷新后重试。',
    workspace_primary_detach_requires_replacement: '解除主工作区需要指定替代工作区。',
    workspace_primary_replacement_required: '注销前请先替换主工作区。',
    workspace_primary_replace_required: '更换主工作区请使用“替换”操作。',
    workspace_primary_not_linked: '主工作区必须已是该项目的活跃关联。',
    workspace_unregister_tasks_pending: '该工作区仍有排队或运行中的任务,无法注销。',

    // 项目上下文
    context_candidate_source_required: '上下文候选必须标注其来源任务。',
    context_candidate_rejected: '已拒绝的候选不能被接受。',
    context_candidate_accepted: '已接受的候选不能被拒绝。',
    context_fragment_source_required: '上下文片段需要指定来源类型。',
    context_fragment_budget_invalid: '上下文片段的字节预算不能为负数。',
    context_preview_expired: '上下文更新预览已过期,请重新预览后再试。',
    context_preview_already_confirmed: '该上下文更新预览已被确认过。',
    context_draft_required: '该项目还没有上下文草稿。',
    context_snapshot_ref_invalid: '所选的上下文快照对该任务无效。',
    context_version_unreviewed: '该项目的上下文产生于版本追踪机制之前,请重新发布项目上下文后再试。',
    context_manifest_missing: '该项目保存的上下文已损坏,请重新发布项目上下文后再试。',
    context_manifest_invalid: '该项目保存的上下文已损坏,请重新发布项目上下文后再试。',

    // 任务
    task_project_required: '创建任务需要选择一个项目。',
    task_workspace_not_linked: '该工作区尚未关联到项目。',
    task_workspace_environment_inactive: '工作区及其运行环境需要处于活跃状态才能运行任务。',
    task_environment_mismatch: '运行环境与该工作区不再匹配,请刷新后重新选择。',
    task_move_turn_active: '移动任务前请先中断进行中的 Turn。',
    task_move_same_project: '该任务已属于目标项目。',
    task_execution_slot_held: '该任务已占用一个执行槽位。',
    fork_transfer_range_invalid: 'Fork 的转移范围无效。',

    // 会话契约错误
    active_turn_exists: '该任务已有一个进行中的 Turn,请等待其结束。',
    expected_turn_mismatch: 'Turn 在你操作时发生了变化,请刷新后重试。',
    turn_not_active: '该 Turn 已不再处于活跃状态。',
    delivery_unknown: '该 Turn 的投递状态未知,请刷新确认。',
    runtime_lost: '运行时连接已丢失,请重试或恢复任务。',
    session_unavailable: '引擎会话暂不可用,请稍后重试。',
    capability_unsupported: '当前引擎不支持此能力。',
    task_not_open: '该任务未处于打开状态,请重新打开后再继续。',
    fork_confirmation_required: 'Fork 前需要先确认预览。',
    migration_required: '该任务需要先完成迁移才能执行此操作,请联系支持。',
    invalid_state_transition: '当前状态下无法执行此操作,请刷新后重试。',
    provider_contract_mismatch: '引擎返回了意外的响应,请重试该操作。',
};

export default errors;
