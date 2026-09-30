export interface ApiErrorDetail {
  code: string
  message: string
  error_type?: string
  details?: Array<Record<string, unknown>>
}

export interface ApiErrorEnvelope { error: ApiErrorDetail }

export interface ThreadSummary {
  thread_id: string
  project_id: string | null
  title: string
  created_at: string
  updated_at: string
  last_turn_number: number
  message_count: number
  preview: string
  last_turn_status: 'running' | 'success' | 'error' | null
}

export interface ProjectSummary {
  id: string
  name: string
  folder_paths: string[]
  primary_path: string
  created_at: string
  is_active: boolean
}

export interface ThreadMessage {
  message_id: string
  turn_number: number
  role: 'user' | 'assistant' | 'tool'
  content: string
  tool_calls: Array<Record<string, unknown>> | null
  tool_call_id: string | null
  created_at: string
}

export interface ThreadArtifact {
  artifact_id: string
  turn_number: number
  name: string
  mime_type: string
  url: string
  operation: 'created' | 'modified'
  tool_call_id: string
  created_at: string
  updated_at: string
}

export interface ApprovalPayload {
  approval_id: string
  tool_call_id: string
  name: string
  args: Record<string, unknown>
  reason?: 'mutation' | 'external_path'
  paths?: Array<{ argument: string; path: string; access: 'read' | 'write' | 'delete' }>
}

export interface TurnResultPayload {
  thread_id: string
  turn_number: number
  input_message_id: string
  status: 'completed' | 'awaiting_approval'
  final_message_id: string | null
  approval: ApprovalPayload | null
  finalization: {
    status: 'completed'
    message: { message_id: string; role: 'assistant'; content: string }
    artifact_ids: string[]
  } | null
}

export interface SseEvent<T = unknown> {
  event: 'status' | 'model_chunk' | 'approval' | 'result' | 'error' | string
  data: T
}
