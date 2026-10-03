import { createId } from '../utils/id.js';

export interface AuditEntry {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  entityType: string;
  entityId?: string;
  metadata: Record<string, unknown>;
}

export interface AuditSink {
  append(entry: AuditEntry): Promise<void>;
  list(limit?: number): Promise<AuditEntry[]>;
}

export function makeAuditEntry(input: Omit<AuditEntry, 'id' | 'timestamp'>): AuditEntry {
  const entry: AuditEntry = {
    id: createId('audit'),
    timestamp: new Date().toISOString(),
    actor: input.actor,
    action: input.action,
    entityType: input.entityType,
    metadata: input.metadata,
  };
  if (input.entityId) entry.entityId = input.entityId;
  return entry;
}
