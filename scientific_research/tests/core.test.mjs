import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CrossrefConnector,
  DeterministicScientificCompiler,
  InMemoryResearchStore,
  LiteratureService,
  ResearchBrain,
  StructuralMatcher,
} from '../dist/index.js';

function mockCrossrefFetch() {
  return async (input) => {
    const url = new URL(String(input));
    assert.equal(url.pathname, '/v1/works');
    assert.equal(url.searchParams.get('query.bibliographic'), 'critical transitions finance');
    return new Response(JSON.stringify({
      message: {
        items: [{
          DOI: '10.1000/test.1',
          title: ['Critical transitions in complex financial networks'],
          author: [{ given: 'Ada', family: 'Researcher', ORCID: 'https://orcid.org/0000-0000-0000-0001' }],
          published: { 'date-parts': [[2026, 7, 2]] },
          'container-title': ['Journal of Complex Systems'],
          abstract: '<jats:p>We propose a nonlinear network model with positive feedback and a critical threshold. We show that network instability increases before a phase transition. We assume stationary sampling within each window. A limitation is sensitivity to window size.</jats:p>',
          URL: 'https://example.org/paper',
          subject: ['Complex Networks', 'Financial Markets'],
          'is-referenced-by-count': 14
        }]
      }
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
}

test('Crossref -> ingest -> compile -> structural match -> audit', async () => {
  const connector = new CrossrefConnector({ fetchImpl: mockCrossrefFetch(), mailto: 'research@example.com' });
  const store = new InMemoryResearchStore();
  const brain = new ResearchBrain({
    literature: new LiteratureService([connector]),
    compiler: new DeterministicScientificCompiler(),
    store,
    matcher: new StructuralMatcher(),
  });

  const search = await brain.searchLiterature({ query: 'critical transitions finance', limit: 5 });
  assert.equal(search.errors.length, 0);
  assert.equal(search.candidates.length, 1);
  assert.equal(search.candidates[0].doi, '10.1000/test.1');
  assert.equal(search.candidates[0].abstract.includes('<'), false);

  const paper = await brain.ingestCandidate(search.candidates[0]);
  assert.equal(paper.access, 'abstract_only');
  assert.equal(paper.authors[0].orcid, '0000-0000-0000-0001');

  const analysis = await brain.compilePaper(paper.id);
  assert.ok(analysis.mechanisms.some((item) => item.mechanism === 'network'));
  assert.ok(analysis.mechanisms.some((item) => item.mechanism === 'feedback'));
  assert.ok(analysis.mechanisms.some((item) => item.mechanism === 'threshold'));
  assert.ok(analysis.claims.length >= 1);
  assert.ok(analysis.assumptions.length >= 1);

  const match = await brain.structuralMatch(paper.id, {
    id: 'bubble-target',
    title: 'Financial bubble detection',
    description: 'Detect self-reinforcing critical market transitions',
    mechanisms: ['network', 'feedback', 'threshold', 'criticality'],
    domain: 'finance',
  });
  assert.ok(match.score > 0.25);
  assert.ok(match.overlappingMechanisms.includes('network'));

  const snapshot = await store.snapshot();
  assert.equal(snapshot.papers, 1);
  assert.equal(snapshot.analyses, 1);
  const audit = await store.list(20);
  assert.ok(audit.some((entry) => entry.action === 'literature.search'));
  assert.ok(audit.some((entry) => entry.action === 'paper.compile'));
  assert.ok(audit.some((entry) => entry.action === 'transfer.structural_match'));
});

test('metadata-only paper is not scientifically compiled', async () => {
  const store = new InMemoryResearchStore();
  const connector = { id: 'fixture', async search() { return [{ provider: 'fixture', sourceId: 'x', title: 'Metadata only', authors: [], subjects: [] }]; } };
  const brain = new ResearchBrain({ literature: new LiteratureService([connector]), compiler: new DeterministicScientificCompiler(), store });
  const result = await brain.searchLiterature({ query: 'x' });
  const paper = await brain.ingestCandidate(result.candidates[0]);
  await assert.rejects(() => brain.compilePaper(paper.id), /metadata only/i);
});

test('local full-text ingestion extracts math and mechanisms', async () => {
  const store = new InMemoryResearchStore();
  const brain = new ResearchBrain({ literature: new LiteratureService([]), compiler: new DeterministicScientificCompiler(), store });
  const paper = await brain.ingestDocument({
    title: 'A multiscale diffusion model',
    text: 'We propose a nonlinear diffusion model with feedback and a threshold. We assume ergodicity. We show a phase transition. The governing equation is \\[ dX_t = -k X_t dt + sigma dW_t \\]. A limitation is finite sample size.',
  });
  const analysis = await brain.compilePaper(paper.id);
  assert.equal(paper.access, 'full_text');
  assert.equal(analysis.equations.length, 1);
  assert.ok(analysis.mechanisms.some((item) => item.mechanism === 'diffusion'));
  assert.ok(analysis.mechanisms.some((item) => item.mechanism === 'multiscale'));
});

test('LiteratureService isolates connector failure and deduplicates DOI', async () => {
  const duplicate = {
    provider: 'a', sourceId: 'a-1', title: 'Same paper', authors: [], subjects: [], doi: '10.1000/duplicate', citationCount: 2
  };
  const service = new LiteratureService([
    { id: 'a', async search() { return [duplicate]; } },
    { id: 'b', async search() { return [{ ...duplicate, provider: 'b', sourceId: 'b-1', citationCount: 99 }]; } },
    { id: 'broken', async search() { throw new Error('temporary outage'); } },
  ]);
  const result = await service.search({ query: 'same' });
  assert.equal(result.candidates.length, 1);
  assert.equal(result.errors.length, 1);
  assert.equal(result.errors[0].connector, 'broken');
});

test('StructuralMatcher labels pure analogy when no mechanism overlaps', () => {
  const matcher = new StructuralMatcher();
  const match = matcher.match({
    id: 'a', paperId: 'p', compiledAt: new Date().toISOString(), problem: 'x', hypotheses: [], assumptions: [], claims: [], limitations: [], equations: [],
    mechanisms: [{ mechanism: 'diffusion', weight: 0.8, evidence: ['diffusion'] }], methods: [], datasets: [], quantTranslation: '', transferIdeas: [], confidence: 0.9, compiler: 'test'
  }, {
    id: 'target', title: 'Bubble', description: '', mechanisms: ['criticality', 'network'], domain: 'finance'
  });
  assert.equal(match.score, 0);
  assert.match(match.warnings[0], /analogy only/i);
});

test('Research quests are first-class persistent objects', async () => {
  const store = new InMemoryResearchStore();
  const brain = new ResearchBrain({ literature: new LiteratureService([]), compiler: new DeterministicScientificCompiler(), store });
  const quest = await brain.createQuest({
    title: 'Bubble early warning',
    description: 'Search cross-domain critical transition mechanisms',
    targetMechanisms: ['Criticality', 'Network', 'Positive Feedback'],
  });
  assert.equal(quest.status, 'open');
  assert.deepEqual(quest.targetMechanisms, ['criticality', 'network', 'positive_feedback']);
  assert.equal((await store.snapshot()).openQuests, 1);
});
