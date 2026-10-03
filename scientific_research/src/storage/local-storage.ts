import type { AuditEntry } from '../audit/log.js';
import type {
  BeliefRecord,
  FailureMemory,
  ResearchQuest,
  ResearchSnapshot,
  ScientificAnalysis,
  ScientificPaper,
  SurpriseMemory,
} from '../domain/types.js';
import type { ResearchStore } from './store.js';

interface PersistedResearchState {
  version: 1;
  papers: ScientificPaper[];
  analyses: ScientificAnalysis[];
  quests: ResearchQuest[];
  failures: FailureMemory[];
  surprises: SurpriseMemory[];
  beliefs: BeliefRecord[];
  audit: AuditEntry[];
}

const EMPTY_STATE: PersistedResearchState = {
  version: 1,
  papers: [],
  analyses: [],
  quests: [],
  failures: [],
  surprises: [],
  beliefs: [],
  audit: [],
};

export class LocalStorageResearchStore implements ResearchStore {
  public constructor(private readonly key = 'wm-scientific-research-v1', private readonly storage: Storage = globalThis.localStorage) {}

  private read(): PersistedResearchState {
    try {
      const raw = this.storage.getItem(this.key);
      if (!raw) return structuredClone(EMPTY_STATE);
      const parsed = JSON.parse(raw) as Partial<PersistedResearchState>;
      if (parsed.version !== 1) return structuredClone(EMPTY_STATE);
      return {
        version: 1,
        papers: Array.isArray(parsed.papers) ? parsed.papers : [],
        analyses: Array.isArray(parsed.analyses) ? parsed.analyses : [],
        quests: Array.isArray(parsed.quests) ? parsed.quests : [],
        failures: Array.isArray(parsed.failures) ? parsed.failures : [],
        surprises: Array.isArray(parsed.surprises) ? parsed.surprises : [],
        beliefs: Array.isArray(parsed.beliefs) ? parsed.beliefs : [],
        audit: Array.isArray(parsed.audit) ? parsed.audit : [],
      };
    } catch {
      return structuredClone(EMPTY_STATE);
    }
  }

  private write(state: PersistedResearchState): void {
    this.storage.setItem(this.key, JSON.stringify(state));
  }

  private upsert<T extends { id: string }>(items: T[], item: T): T[] {
    return [...items.filter((existing) => existing.id !== item.id), structuredClone(item)];
  }

  public async putPaper(paper: ScientificPaper): Promise<void> { const s = this.read(); s.papers = this.upsert(s.papers, paper); this.write(s); }
  public async getPaper(id: string): Promise<ScientificPaper | undefined> { const v = this.read().papers.find((item) => item.id === id); return v ? structuredClone(v) : undefined; }
  public async listPapers(): Promise<ScientificPaper[]> { return this.read().papers.map((v) => structuredClone(v)); }
  public async putAnalysis(analysis: ScientificAnalysis): Promise<void> { const s = this.read(); s.analyses = [...s.analyses.filter((item) => item.paperId !== analysis.paperId), structuredClone(analysis)]; this.write(s); }
  public async getAnalysisForPaper(paperId: string): Promise<ScientificAnalysis | undefined> { const v = this.read().analyses.find((item) => item.paperId === paperId); return v ? structuredClone(v) : undefined; }
  public async listAnalyses(): Promise<ScientificAnalysis[]> { return this.read().analyses.map((v) => structuredClone(v)); }
  public async putQuest(quest: ResearchQuest): Promise<void> { const s = this.read(); s.quests = this.upsert(s.quests, quest); this.write(s); }
  public async listQuests(): Promise<ResearchQuest[]> { return this.read().quests.map((v) => structuredClone(v)); }
  public async putFailure(failure: FailureMemory): Promise<void> { const s = this.read(); s.failures = this.upsert(s.failures, failure); this.write(s); }
  public async listFailures(): Promise<FailureMemory[]> { return this.read().failures.map((v) => structuredClone(v)); }
  public async putSurprise(surprise: SurpriseMemory): Promise<void> { const s = this.read(); s.surprises = this.upsert(s.surprises, surprise); this.write(s); }
  public async listSurprises(): Promise<SurpriseMemory[]> { return this.read().surprises.map((v) => structuredClone(v)); }
  public async putBelief(belief: BeliefRecord): Promise<void> { const s = this.read(); s.beliefs = this.upsert(s.beliefs, belief); this.write(s); }
  public async listBeliefs(): Promise<BeliefRecord[]> { return this.read().beliefs.map((v) => structuredClone(v)); }
  public async append(entry: AuditEntry): Promise<void> { const s = this.read(); s.audit = [...s.audit.slice(-1999), structuredClone(entry)]; this.write(s); }
  public async list(limit = 100): Promise<AuditEntry[]> { return this.read().audit.slice(-Math.max(0, limit)).reverse().map((v) => structuredClone(v)); }

  public async snapshot(): Promise<ResearchSnapshot> {
    const s = this.read();
    const timestamps = [
      ...s.papers.map((item) => item.ingestedAt),
      ...s.analyses.map((item) => item.compiledAt),
      ...s.quests.map((item) => item.updatedAt),
    ].sort();
    const snapshot: ResearchSnapshot = {
      papers: s.papers.length,
      analyses: s.analyses.length,
      quests: s.quests.length,
      failures: s.failures.length,
      surprises: s.surprises.length,
      beliefs: s.beliefs.length,
      openQuests: s.quests.filter((quest) => quest.status === 'open').length,
    };
    const lastUpdatedAt = timestamps.at(-1);
    if (lastUpdatedAt) snapshot.lastUpdatedAt = lastUpdatedAt;
    return snapshot;
  }
}
