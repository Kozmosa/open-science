import type {
  TerminalSessionResponse,
  TerminalSessionStatus as TransportTerminalSessionStatus,
  UserSessionPairResponse,
} from '@/generated/transport';

export type TerminalSessionStatus = TransportTerminalSessionStatus;
export type TerminalAttachmentMode = 'write' | 'observe';

export type TerminalSession = {
  session_id: string | null;
  provider: 'pty' | 'tmux';
  target_kind: string;
  environment_id: string | null;
  environment_alias: string | null;
  working_directory: string | null;
  status: TerminalSessionStatus;
  created_at: string | null;
  started_at: string | null;
  closed_at: string | null;
  terminal_ws_url: string | null;
  detail: string | null;
  binding_id: string | null;
  session_name: string | null;
  attachment_id: string | null;
  attachment_expires_at: string | null;
};

export type UserSessionPair = {
  binding_id: string;
  environment_id: string;
  environment_alias: string | null;
  personal_session_name: string;
  agent_session_name: string | null;
  personal_status: TerminalSessionStatus;
  agent_status: TerminalSessionStatus | null;
  created_at: string | null;
  updated_at: string | null;
  last_verified_at: string | null;
  last_personal_attach_at: string | null;
  last_agent_attach_at: string | null;
  detail: string | null;
};

export type UserSessionPairListResponse = { items: UserSessionPair[] };

export function adaptTerminalSession(value: TerminalSessionResponse): TerminalSession {
  return {
    session_id: value.session_id ?? null,
    provider: value.provider === 'tmux' ? 'tmux' : 'pty',
    target_kind: value.target_kind ?? 'environment',
    environment_id: value.environment_id ?? null,
    environment_alias: value.environment_alias ?? null,
    working_directory: value.working_directory ?? null,
    status: value.status,
    created_at: value.created_at ?? null,
    started_at: value.started_at ?? null,
    closed_at: value.closed_at ?? null,
    terminal_ws_url: value.terminal_ws_url ?? null,
    detail: value.detail ?? null,
    binding_id: value.binding_id ?? null,
    session_name: value.session_name ?? null,
    attachment_id: value.attachment_id ?? null,
    attachment_expires_at: value.attachment_expires_at ?? null,
  };
}

export function adaptSessionPairs(value: { items: UserSessionPairResponse[] }): UserSessionPairListResponse {
  return {
    items: value.items.map((item) => ({
      binding_id: item.binding_id,
      environment_id: item.environment_id,
      environment_alias: item.environment_alias ?? null,
      personal_session_name: item.personal_session_name,
      agent_session_name: item.agent_session_name ?? null,
      personal_status: item.personal_status,
      agent_status: item.agent_status ?? null,
      created_at: item.created_at ?? null,
      updated_at: item.updated_at ?? null,
      last_verified_at: item.last_verified_at ?? null,
      last_personal_attach_at: item.last_personal_attach_at ?? null,
      last_agent_attach_at: item.last_agent_attach_at ?? null,
      detail: item.detail ?? null,
    })),
  };
}
