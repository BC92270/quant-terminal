export type ScientificDomain =
  | 'mathematics'
  | 'statistics'
  | 'physics'
  | 'computer_science'
  | 'biology'
  | 'economics'
  | 'finance'
  | 'engineering'
  | 'multidisciplinary'
  | 'unknown';

export type EvidenceStatus = 'unknown' | 'speculative' | 'supported' | 'contested' | 'strong' | 'rejected';

export type PaperAccess = 'metadata_only' | 'abstract_only' | 'full_text';

export interface AuthorIdentity {
  name: string;
  orcid?: string;
  affiliation?: string;
}

export interface LiteratureSourceRef {
  provider: string;
  sourceId: string;
  url?: string;
  doi?: string;
}

export interface ScientificPaper {
  id: string;
  title: string;
  authors: AuthorIdentity[];
  publishedAt?: string;
  venue?: string;
  doi?: string;
  url?: string;
  abstract?: string;
  fullText?: string;
  access: PaperAccess;
  domain: ScientificDomain;
  subjects: string[];
  citationCount?: number;
  source: LiteratureSourceRef;
  ingestedAt: string;
}

export interface EquationObject {
  raw: string;
  normalized?: string;
  variables: string[];
  operators: string[];
  confidence: number;
}

export interface MechanismWeight {
  mechanism: string;
  weight: number;
  evidence: string[];
}

export interface ScientificAnalysis {
  id: string;
  paperId: string;
  compiledAt: string;
  problem: string;
  hypotheses: string[];
  assumptions: string[];
  claims: string[];
  limitations: string[];
  equations: EquationObject[];
  mechanisms: MechanismWeight[];
  methods: string[];
  datasets: string[];
  quantTranslation: string;
  transferIdeas: string[];
  confidence: number;
  compiler: string;
}

export interface ResearchQuest {
  id: string;
  title: string;
  description: string;
  targetMechanisms: string[];
  status: 'open' | 'paused' | 'completed' | 'rejected';
  createdAt: string;
  updatedAt: string;
}

export interface FailureMemory {
  id: string;
  createdAt: string;
  context: string;
  hypothesis?: string;
  reason: string;
  retryConditions: string[];
  relatedEntityIds: string[];
}

export interface SurpriseMemory {
  id: string;
  createdAt: string;
  expectation: string;
  observation: string;
  surpriseScore: number;
  generatedQuestions: string[];
  relatedEntityIds: string[];
}

export interface BeliefRecord {
  id: string;
  claim: string;
  status: EvidenceStatus;
  confidence: number;
  evidenceFor: string[];
  evidenceAgainst: string[];
  updatedAt: string;
}

export interface TargetProblem {
  id: string;
  title: string;
  description: string;
  mechanisms: string[];
  domain: string;
}

export interface StructuralMatch {
  sourcePaperId: string;
  targetProblemId: string;
  score: number;
  overlappingMechanisms: string[];
  missingTargetMechanisms: string[];
  sourceOnlyMechanisms: string[];
  rationale: string[];
  warnings: string[];
}

export interface ResearchSnapshot {
  papers: number;
  analyses: number;
  quests: number;
  failures: number;
  surprises: number;
  beliefs: number;
  openQuests: number;
  lastUpdatedAt?: string;
}
