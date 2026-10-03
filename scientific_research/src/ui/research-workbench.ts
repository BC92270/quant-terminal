import type { LiteratureCandidate } from '../literature/types.js';
import type { AuditEntry } from '../audit/log.js';
import type { ScientificAnalysis, ScientificPaper, StructuralMatch, TargetProblem } from '../domain/types.js';
import type { ResearchBrain } from '../core/research-brain.js';
import { createId } from '../utils/id.js';

export interface ResearchWorkbenchOptions {
  brain: ResearchBrain;
  title?: string;
}

const STYLE_ID = 'srb-phase1-style';

const CSS = `
.srb{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;color:var(--text-primary,#dbe7f3);background:var(--bg-primary,#071018);min-height:640px;padding:14px;box-sizing:border-box}
.srb *{box-sizing:border-box}.srb h2,.srb h3{margin:0}.srb__header{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;border-bottom:1px solid rgba(148,163,184,.22);padding-bottom:12px}.srb__eyebrow{font-size:10px;letter-spacing:.18em;color:#7dd3fc}.srb__title{font-size:19px;letter-spacing:.03em}.srb__status{font-size:10px;color:#86efac}.srb__grid{display:grid;grid-template-columns:repeat(6,minmax(92px,1fr));gap:8px;margin:12px 0}.srb__metric{border:1px solid rgba(148,163,184,.2);background:rgba(15,23,42,.65);padding:9px}.srb__metric b{display:block;font-size:18px}.srb__metric span{font-size:9px;color:#94a3b8;text-transform:uppercase}.srb__cols{display:grid;grid-template-columns:minmax(300px,.95fr) minmax(380px,1.35fr);gap:12px}.srb__card{border:1px solid rgba(148,163,184,.2);background:rgba(8,15,25,.85);padding:12px;margin-bottom:12px}.srb__card h3{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:#cbd5e1;margin-bottom:10px}.srb__row{display:flex;gap:7px}.srb input,.srb textarea,.srb button{font:inherit}.srb input,.srb textarea{width:100%;background:#08111d;border:1px solid rgba(148,163,184,.25);color:#e2e8f0;padding:8px}.srb textarea{min-height:72px;resize:vertical}.srb button{border:1px solid rgba(125,211,252,.45);background:rgba(14,116,144,.14);color:#bae6fd;padding:7px 10px;cursor:pointer}.srb button:hover{background:rgba(14,116,144,.3)}.srb button:disabled{opacity:.45;cursor:not-allowed}.srb__list{max-height:260px;overflow:auto}.srb__item{width:100%;text-align:left;border:0!important;border-bottom:1px solid rgba(148,163,184,.12)!important;background:transparent!important;padding:9px 3px!important}.srb__item strong{display:block;color:#e2e8f0;font-size:11px}.srb__item small{color:#64748b}.srb__muted{color:#64748b;font-size:10px}.srb__tag{display:inline-block;border:1px solid rgba(148,163,184,.25);padding:2px 5px;margin:2px;font-size:9px;color:#cbd5e1}.srb__score{font-size:30px;font-weight:700}.srb__warning{border-left:2px solid #fbbf24;padding-left:8px;color:#fde68a;font-size:10px;margin:5px 0}.srb__error{color:#fca5a5;font-size:10px}.srb__ok{color:#86efac;font-size:10px}.srb__section{margin-top:10px}.srb__section b{font-size:10px;color:#94a3b8;text-transform:uppercase}.srb__section p{font-size:11px;line-height:1.55;margin:4px 0}.srb__audit{font-size:9px;color:#94a3b8;border-top:1px solid rgba(148,163,184,.12);padding:5px 0}@media(max-width:900px){.srb__grid{grid-template-columns:repeat(3,1fr)}.srb__cols{grid-template-columns:1fr}}
`;

function ensureStyles(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.appendChild(style);
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function addSection(parent: HTMLElement, title: string, values: readonly string[]): void {
  if (!values.length) return;
  const section = el('div', 'srb__section');
  section.appendChild(el('b', undefined, title));
  for (const value of values.slice(0, 8)) section.appendChild(el('p', undefined, value));
  parent.appendChild(section);
}

export class ResearchWorkbench {
  private readonly brain: ResearchBrain;
  private readonly title: string;
  private root: HTMLElement | null = null;
  private candidates: LiteratureCandidate[] = [];
  private selectedPaperId: string | null = null;
  private status = 'READY';
  private error = '';
  private currentMatch: StructuralMatch | null = null;

  public constructor(options: ResearchWorkbenchOptions) {
    this.brain = options.brain;
    this.title = options.title ?? 'Scientific Research Brain';
  }

  public async mount(container: HTMLElement): Promise<void> {
    ensureStyles();
    this.root = el('section', 'srb');
    container.replaceChildren(this.root);
    await this.render();
  }

  public destroy(): void {
    this.root?.remove();
    this.root = null;
  }

  private async render(): Promise<void> {
    if (!this.root) return;
    const store = this.brain.getStore();
    const [snapshot, papers, audit] = await Promise.all([store.snapshot(), store.listPapers(), store.list(8)]);
    this.root.replaceChildren();

    const header = el('div', 'srb__header');
    const left = el('div');
    left.appendChild(el('div', 'srb__eyebrow', 'SCIENTIFIC INTELLIGENCE / PHASE 1'));
    left.appendChild(el('h2', 'srb__title', this.title));
    header.appendChild(left);
    header.appendChild(el('div', 'srb__status', this.status));
    this.root.appendChild(header);

    const metrics = el('div', 'srb__grid');
    const metricData: Array<[string, number]> = [
      ['Papers', snapshot.papers], ['Compiled', snapshot.analyses], ['Quests', snapshot.openQuests],
      ['Failures', snapshot.failures], ['Surprises', snapshot.surprises], ['Beliefs', snapshot.beliefs],
    ];
    for (const [label, value] of metricData) {
      const metric = el('div', 'srb__metric');
      metric.appendChild(el('b', undefined, String(value)));
      metric.appendChild(el('span', undefined, label));
      metrics.appendChild(metric);
    }
    this.root.appendChild(metrics);

    if (this.error) this.root.appendChild(el('div', 'srb__error', this.error));

    const cols = el('div', 'srb__cols');
    const leftCol = el('div');
    const rightCol = el('div');
    leftCol.appendChild(this.renderSearchCard());
    leftCol.appendChild(this.renderMemoryCard(papers));
    leftCol.appendChild(this.renderQuestCard());
    rightCol.appendChild(await this.renderPaperCard(papers));
    rightCol.appendChild(await this.renderAuditCard(audit));
    cols.append(leftCol, rightCol);
    this.root.appendChild(cols);
  }

  private renderSearchCard(): HTMLElement {
    const card = el('div', 'srb__card');
    card.appendChild(el('h3', undefined, 'Literature Intelligence'));
    const row = el('div', 'srb__row');
    const input = el('input');
    input.placeholder = 'Search Crossref: random matrix theory financial networks…';
    const button = el('button', undefined, 'SEARCH');
    row.append(input, button);
    card.appendChild(row);
    const message = el('div', 'srb__muted', 'Metadata search only. Full-text acquisition is deliberately separated from metadata ingestion.');
    card.appendChild(message);

    button.addEventListener('click', () => void this.runSearch(input.value, button));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') void this.runSearch(input.value, button);
    });

    const list = el('div', 'srb__list');
    for (const candidate of this.candidates) {
      const item = el('button', 'srb__item');
      item.appendChild(el('strong', undefined, candidate.title));
      item.appendChild(el('small', undefined, `${candidate.publishedAt ?? 'undated'} · ${candidate.venue ?? candidate.provider} · ${candidate.citationCount ?? 0} citations`));
      item.addEventListener('click', () => void this.ingest(candidate));
      list.appendChild(item);
    }
    card.appendChild(list);
    return card;
  }

  private renderMemoryCard(papers: readonly ScientificPaper[]): HTMLElement {
    const card = el('div', 'srb__card');
    card.appendChild(el('h3', undefined, 'Scientific Memory'));
    if (!papers.length) {
      card.appendChild(el('div', 'srb__muted', 'No papers stored yet.'));
      return card;
    }
    const list = el('div', 'srb__list');
    for (const paper of [...papers].reverse().slice(0, 30)) {
      const item = el('button', 'srb__item');
      item.appendChild(el('strong', undefined, paper.title));
      item.appendChild(el('small', undefined, `${paper.domain} · ${paper.access}`));
      item.addEventListener('click', () => { this.selectedPaperId = paper.id; this.currentMatch = null; void this.render(); });
      list.appendChild(item);
    }
    card.appendChild(list);
    return card;
  }

  private renderQuestCard(): HTMLElement {
    const card = el('div', 'srb__card');
    card.appendChild(el('h3', undefined, 'Research Quest'));
    const title = el('input');
    title.placeholder = 'Quest title';
    const description = el('textarea');
    description.placeholder = 'Research objective / unknown to explore';
    const mechanisms = el('input');
    mechanisms.placeholder = 'mechanisms: criticality, network, threshold, feedback';
    const button = el('button', undefined, 'CREATE QUEST');
    card.append(title, description, mechanisms, button);
    button.addEventListener('click', () => void (async () => {
      if (!title.value.trim() || !description.value.trim()) return;
      this.status = 'CREATING QUEST';
      await this.brain.createQuest({ title: title.value, description: description.value, targetMechanisms: mechanisms.value.split(',') });
      this.status = 'READY';
      await this.render();
    })());
    return card;
  }

  private async renderPaperCard(papers: readonly ScientificPaper[]): Promise<HTMLElement> {
    const card = el('div', 'srb__card');
    card.appendChild(el('h3', undefined, 'Scientific Compiler / Structural Transfer'));
    const paper = papers.find((item) => item.id === this.selectedPaperId) ?? papers.at(-1);
    if (!paper) {
      card.appendChild(el('div', 'srb__muted', 'Select or ingest a paper to begin.'));
      return card;
    }
    this.selectedPaperId = paper.id;
    card.appendChild(el('div', 'srb__section', paper.title));
    card.appendChild(el('div', 'srb__muted', `${paper.domain} · ${paper.access} · ${paper.doi ?? paper.source.sourceId}`));
    const analysis = await this.brain.getStore().getAnalysisForPaper(paper.id);
    if (!analysis) {
      const compile = el('button', undefined, paper.access === 'metadata_only' ? 'ABSTRACT/FULL TEXT REQUIRED' : 'COMPILE PAPER');
      compile.disabled = paper.access === 'metadata_only';
      compile.addEventListener('click', () => void this.compilePaper(paper.id, compile));
      card.appendChild(compile);
      if (paper.access === 'metadata_only') card.appendChild(el('div', 'srb__warning', 'Crossref returned metadata without abstract. Phase 1 refuses to fabricate scientific content.'));
      return card;
    }

    this.appendAnalysis(card, analysis);
    card.appendChild(this.renderTransferForm(paper.id));
    if (this.currentMatch?.sourcePaperId === paper.id) this.appendMatch(card, this.currentMatch);
    return card;
  }

  private appendAnalysis(card: HTMLElement, analysis: ScientificAnalysis): void {
    addSection(card, 'Problem', [analysis.problem]);
    addSection(card, 'Claims', analysis.claims);
    addSection(card, 'Assumptions', analysis.assumptions);
    addSection(card, 'Limitations', analysis.limitations);
    if (analysis.mechanisms.length) {
      const section = el('div', 'srb__section');
      section.appendChild(el('b', undefined, 'Mechanism signature'));
      for (const mechanism of analysis.mechanisms) section.appendChild(el('span', 'srb__tag', `${mechanism.mechanism} ${(mechanism.weight * 100).toFixed(0)}%`));
      card.appendChild(section);
    }
    addSection(card, 'Quant translation', [analysis.quantTranslation]);
    addSection(card, 'Transfer ideas — hypotheses only', analysis.transferIdeas);
    card.appendChild(el('div', 'srb__muted', `Compiler ${analysis.compiler} · confidence ${(analysis.confidence * 100).toFixed(0)}%`));
  }

  private renderTransferForm(paperId: string): HTMLElement {
    const section = el('div', 'srb__section');
    section.appendChild(el('b', undefined, 'Structural matching — not semantic analogy'));
    const title = el('input');
    title.placeholder = 'Target: financial bubble detection';
    const mechanisms = el('input');
    mechanisms.placeholder = 'criticality, feedback, threshold, network';
    const button = el('button', undefined, 'MATCH STRUCTURE');
    section.append(title, mechanisms, button);
    button.addEventListener('click', () => void (async () => {
      const target: TargetProblem = {
        id: createId('target'),
        title: title.value.trim() || 'Financial target',
        description: title.value.trim(),
        mechanisms: mechanisms.value.split(',').map((item) => item.trim()).filter(Boolean),
        domain: 'finance',
      };
      this.currentMatch = await this.brain.structuralMatch(paperId, target);
      await this.render();
    })());
    return section;
  }

  private appendMatch(card: HTMLElement, match: StructuralMatch): void {
    const section = el('div', 'srb__section');
    section.appendChild(el('b', undefined, 'Transfer audit — first pass'));
    section.appendChild(el('div', 'srb__score', `${(match.score * 100).toFixed(0)}/100`));
    for (const rationale of match.rationale) section.appendChild(el('p', undefined, rationale));
    for (const warning of match.warnings) section.appendChild(el('div', 'srb__warning', warning));
    card.appendChild(section);
  }

  private async renderAuditCard(audit: readonly AuditEntry[]): Promise<HTMLElement> {
    const card = el('div', 'srb__card');
    card.appendChild(el('h3', undefined, 'Audit Trail'));
    for (const entry of audit) card.appendChild(el('div', 'srb__audit', `${entry.timestamp} · ${entry.actor} · ${entry.action}`));
    return card;
  }

  private async runSearch(query: string, button: HTMLButtonElement): Promise<void> {
    if (!query.trim()) return;
    this.error = '';
    this.status = 'SCANNING LITERATURE';
    button.disabled = true;
    try {
      const result = await this.brain.searchLiterature({ query, limit: 12 });
      this.candidates = result.candidates;
      if (result.errors.length) this.error = result.errors.map((item) => `${item.connector}: ${item.message}`).join(' · ');
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
    } finally {
      button.disabled = false;
      this.status = 'READY';
      await this.render();
    }
  }

  private async ingest(candidate: LiteratureCandidate): Promise<void> {
    this.error = '';
    this.status = 'INGESTING';
    try {
      const paper = await this.brain.ingestCandidate(candidate);
      this.selectedPaperId = paper.id;
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
    } finally {
      this.status = 'READY';
      await this.render();
    }
  }

  private async compilePaper(paperId: string, button: HTMLButtonElement): Promise<void> {
    this.error = '';
    this.status = 'COMPILING SCIENCE';
    button.disabled = true;
    try {
      await this.brain.compilePaper(paperId);
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
    } finally {
      button.disabled = false;
      this.status = 'READY';
      await this.render();
    }
  }
}
