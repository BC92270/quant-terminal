import { makeAuditEntry } from '../audit/log.js';
import type { ScientificCompiler } from '../compiler/types.js';
import { StructuralMatcher } from '../discovery/structural-matcher.js';
import type {
  ResearchQuest,
  ScientificAnalysis,
  ScientificPaper,
  StructuralMatch,
  TargetProblem,
} from '../domain/types.js';
import { inferDomain } from '../ontology/mechanisms.js';
import type { LiteratureSearchRequest, LiteratureCandidate } from '../literature/types.js';
import type { LiteratureSearchResult } from '../literature/service.js';
import { LiteratureService } from '../literature/service.js';
import type { ResearchStore } from '../storage/store.js';
import { createId } from '../utils/id.js';

export interface ResearchBrainOptions {
  literature: LiteratureService;
  compiler: ScientificCompiler;
  store: ResearchStore;
  matcher?: StructuralMatcher;
}

export class ResearchBrain {
  private readonly literature: LiteratureService;
  private readonly compiler: ScientificCompiler;
  private readonly store: ResearchStore;
  private readonly matcher: StructuralMatcher;

  public constructor(options: ResearchBrainOptions) {
    this.literature = options.literature;
    this.compiler = options.compiler;
    this.store = options.store;
    this.matcher = options.matcher ?? new StructuralMatcher();
  }

  public getStore(): ResearchStore {
    return this.store;
  }

  public async searchLiterature(request: LiteratureSearchRequest, signal?: AbortSignal): Promise<LiteratureSearchResult> {
    const result = await this.literature.search(request, signal);
    await this.store.append(makeAuditEntry({
      actor: 'literature-agent',
      action: 'literature.search',
      entityType: 'query',
      metadata: { query: request.query, candidates: result.candidates.length, errors: result.errors },
    }));
    return result;
  }

  public async ingestCandidate(candidate: LiteratureCandidate): Promise<ScientificPaper> {
    const existing = (await this.store.listPapers()).find((paper) =>
      (candidate.doi && paper.doi?.toLowerCase() === candidate.doi.toLowerCase()) ||
      (paper.source.provider === candidate.provider && paper.source.sourceId === candidate.sourceId),
    );
    if (existing) return existing;

    const domainText = [candidate.title, candidate.abstract, candidate.subjects.join(' ')].filter(Boolean).join(' ');
    const paper: ScientificPaper = {
      id: createId('paper'),
      title: candidate.title,
      authors: candidate.authors,
      access: candidate.abstract ? 'abstract_only' : 'metadata_only',
      domain: inferDomain(domainText),
      subjects: candidate.subjects,
      source: {
        provider: candidate.provider,
        sourceId: candidate.sourceId,
      },
      ingestedAt: new Date().toISOString(),
    };
    if (candidate.publishedAt) paper.publishedAt = candidate.publishedAt;
    if (candidate.venue) paper.venue = candidate.venue;
    if (candidate.doi) {
      paper.doi = candidate.doi;
      paper.source.doi = candidate.doi;
    }
    if (candidate.url) {
      paper.url = candidate.url;
      paper.source.url = candidate.url;
    }
    if (candidate.abstract) paper.abstract = candidate.abstract;
    if (candidate.citationCount !== undefined) paper.citationCount = candidate.citationCount;

    await this.store.putPaper(paper);
    await this.store.append(makeAuditEntry({
      actor: 'memory-curator',
      action: 'paper.ingest',
      entityType: 'paper',
      entityId: paper.id,
      metadata: { provider: candidate.provider, doi: candidate.doi ?? null, access: paper.access },
    }));
    return paper;
  }

  public async ingestDocument(input: {
    title: string;
    text: string;
    authors?: ScientificPaper['authors'];
    abstract?: string;
    doi?: string;
    url?: string;
    subjects?: string[];
  }): Promise<ScientificPaper> {
    const now = new Date().toISOString();
    const paper: ScientificPaper = {
      id: createId('paper'),
      title: input.title.trim(),
      authors: input.authors ?? [],
      fullText: input.text,
      access: 'full_text',
      domain: inferDomain(`${input.title} ${input.abstract ?? ''} ${input.text.slice(0, 5000)}`),
      subjects: input.subjects ?? [],
      source: { provider: 'local', sourceId: createId('local-document') },
      ingestedAt: now,
    };
    if (input.abstract) paper.abstract = input.abstract;
    if (input.doi) {
      paper.doi = input.doi;
      paper.source.doi = input.doi;
    }
    if (input.url) {
      paper.url = input.url;
      paper.source.url = input.url;
    }
    await this.store.putPaper(paper);
    await this.store.append(makeAuditEntry({
      actor: 'memory-curator',
      action: 'paper.ingest_local',
      entityType: 'paper',
      entityId: paper.id,
      metadata: { chars: input.text.length, access: paper.access },
    }));
    return paper;
  }

  public async compilePaper(paperId: string, signal?: AbortSignal): Promise<ScientificAnalysis> {
    const paper = await this.store.getPaper(paperId);
    if (!paper) throw new Error(`Paper not found: ${paperId}`);
    if (!paper.abstract && !paper.fullText) throw new Error('Paper has metadata only. Add an abstract or full text before scientific compilation.');
    const analysis = await this.compiler.compile(paper, signal);
    await this.store.putAnalysis(analysis);
    await this.store.append(makeAuditEntry({
      actor: 'scientific-compiler',
      action: 'paper.compile',
      entityType: 'paper',
      entityId: paperId,
      metadata: { compiler: analysis.compiler, confidence: analysis.confidence, mechanisms: analysis.mechanisms.length },
    }));
    return analysis;
  }

  public async createQuest(input: { title: string; description: string; targetMechanisms?: string[] }): Promise<ResearchQuest> {
    const now = new Date().toISOString();
    const quest: ResearchQuest = {
      id: createId('quest'),
      title: input.title.trim(),
      description: input.description.trim(),
      targetMechanisms: input.targetMechanisms?.map((item) => item.trim().toLowerCase().replace(/[\s-]+/g, '_')).filter(Boolean) ?? [],
      status: 'open',
      createdAt: now,
      updatedAt: now,
    };
    await this.store.putQuest(quest);
    await this.store.append(makeAuditEntry({
      actor: 'research-director',
      action: 'quest.create',
      entityType: 'quest',
      entityId: quest.id,
      metadata: { mechanisms: quest.targetMechanisms },
    }));
    return quest;
  }

  public async structuralMatch(paperId: string, target: TargetProblem): Promise<StructuralMatch> {
    const analysis = await this.store.getAnalysisForPaper(paperId);
    if (!analysis) throw new Error('Compile the paper before structural matching.');
    const result = this.matcher.match(analysis, target);
    await this.store.append(makeAuditEntry({
      actor: 'discovery-agent',
      action: 'transfer.structural_match',
      entityType: 'paper',
      entityId: paperId,
      metadata: { target: target.title, score: result.score, overlap: result.overlappingMechanisms },
    }));
    return result;
  }
}
