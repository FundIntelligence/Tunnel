// 'checking' is the genuine initial value: we haven't yet confirmed whether this
// deal has prior analysis results. 'idle' means we CONCLUSIVELY confirmed there
// are none — the two must never be conflated, or a not-yet-checked deal renders
// identically to a genuinely-never-analysed one (see PAR-91 rehydration fix).
export type AnalysisState = 'checking' | 'idle' | 'uploading' | 'polling' | 'exporting' | 'done' | 'error';

export interface QueuedStatement {
  id: string;
  fileName: string;
  status: 'uploading' | 'processing' | 'ready' | 'failed';
}

export interface EntityBreakdownRow {
  entityId: string;
  entityName: string;
  role: string;
  totalAbsCents: number;
  pctBps: number; // basis points, display as pctBps/100 + '%'
  txnCount: number;
}

export type StageStatus = 'done' | 'active' | 'queued' | 'failed';

export interface PipelineStage {
  name: string;
  detail: string;
  progress: string;
  pct?: number;
  status: StageStatus;
}

export interface DrillModalState {
  title: string;
  color: string;
  rows: Array<Record<string, unknown>>;
  type: 'entity' | 'txn';
}

export interface ParserRequestDoc {
  docId: string;
  fileName: string;
  errorMessage: string;
}

export interface ParserRequestForm {
  bankName: string;
  country: string;
  accountType: string;
  notes: string;
}
