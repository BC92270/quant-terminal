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

export class InMemoryResearchStore implements ResearchStore {
  private readonly papers = new Map<string, ScientificPaper>();
  private readonly analyses = new Map<string, ScientificAnalysis>();
  private readonly quests = new Map<string, ResearchQuest>();
  private readonly failures = new Map<string, FailureMemory>();
  private readonly surprises = new Map<string, SurpriseMemory>();
  private readonly beliefs = new Map<string, BeliefRecord>();
  private readonly audit: AuditEntry[] = [];

  public async putPaper(paper: ScientificPaper): Promise<void> { this.papers.set(paper.id, structuredClone(paper)); }
  public async getPaper(id: string): Promise<ScientificPaper | undefined> { const v = this.papers.get(id); return v ? structuredClone(v) : undefined; }
  public async listPapers(): Promise<ScientificPaper[]> { return [...this.papers.values()].map((v) => structuredClone(v)); }
  public async putAnalysis(analysis: ScientificAnalysis): Promise<void> { this.analyses.set(analysis.paperId, structuredClone(analysis)); }
  public async getAnalysisForPaper(paperId: string): Promise<ScientificAnalysis | undefined> { const v = this.analyses.get(paperId); return v ? structuredClone(v) : undefined; }
  public async listAnalyses(): Promise<ScientificAnalysis[]> { return [...this.analyses.values()].map((v) => structuredClone(v)); }
  public async putQuest(quest: ResearchQuest): Promise<void> { this.quests.set(quest.id, structuredClone(quest)); }
  public async listQuests(): Promise<ResearchQuest[]> { return [...this.quests.values()].map((v) => structuredClone(v)); }
  public async putFailure(failure: FailureMemory): Promise<void> { this.failures.set(failure.id, structuredClone(failure)); }
  public async listFailures(): Promise<FailureMemory[]> { return [...this.failures.values()].map((v) => structuredClone(v)); }
  public async putSurprise(surprise: SurpriseMemory): Promise<void> { this.surprises.set(surprise.id, structuredClone(surprise)); }
  public async listSurprises(): Promise<SurpriseMemory[]> { return [...this.surprises.values()].map((v) => structuredClone(v)); }
  public async putBelief(belief: BeliefRecord): Promise<void> { this.beliefs.set(belief.id, structuredClone(belief)); }
  public async listBeliefs(): Promise<BeliefRecord[]> { return [...this.beliefs.values()].map((v) => structuredClone(v)); }
  public async append(entry: AuditEntry): Promise<void> { this.audit.push(structuredClone(entry)); }
  public async list(limit = 100): Promise<AuditEntry[]> { return this.audit.slice(-Math.max(0, limit)).reverse().map((v) => structuredClone(v)); }

  public async snapshot(): Promise<ResearchSnapshot> {
    const quests = [...this.quests.values()];
    const timestamps = [
      ...[...this.papers.values()].map((item) => item.ingestedAt),
      ...[...this.analyses.values()].map((item) => item.compiledAt),
      ...quests.map((item) => item.updatedAt),
    ].sort();
    const snapshot: ResearchSnapshot = {
      papers: this.papers.size,
      analyses: this.analyses.size,
      quests: this.quests.size,
      failures: this.failures.size,
      surprises: this.surprises.size,
      beliefs: this.beliefs.size,
      openQuests: quests.filter((quest) => quest.status === 'open').length,
    };
    const lastUpdatedAt = timestamps.at(-1);
    if (lastUpdatedAt) snapshot.lastUpdatedAt = lastUpdatedAt;
    return snapshot;
  }
}
