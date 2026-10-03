import type {
  BeliefRecord,
  FailureMemory,
  ResearchQuest,
  ResearchSnapshot,
  ScientificAnalysis,
  ScientificPaper,
  SurpriseMemory,
} from '../domain/types.js';
import type { AuditEntry, AuditSink } from '../audit/log.js';

export interface ResearchStore extends AuditSink {
  putPaper(paper: ScientificPaper): Promise<void>;
  getPaper(id: string): Promise<ScientificPaper | undefined>;
  listPapers(): Promise<ScientificPaper[]>;
  putAnalysis(analysis: ScientificAnalysis): Promise<void>;
  getAnalysisForPaper(paperId: string): Promise<ScientificAnalysis | undefined>;
  listAnalyses(): Promise<ScientificAnalysis[]>;
  putQuest(quest: ResearchQuest): Promise<void>;
  listQuests(): Promise<ResearchQuest[]>;
  putFailure(failure: FailureMemory): Promise<void>;
  listFailures(): Promise<FailureMemory[]>;
  putSurprise(surprise: SurpriseMemory): Promise<void>;
  listSurprises(): Promise<SurpriseMemory[]>;
  putBelief(belief: BeliefRecord): Promise<void>;
  listBeliefs(): Promise<BeliefRecord[]>;
  snapshot(): Promise<ResearchSnapshot>;
  list(limit?: number): Promise<AuditEntry[]>;
}
