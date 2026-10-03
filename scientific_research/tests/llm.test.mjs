import test from 'node:test';
import assert from 'node:assert/strict';
import { LlmScientificCompiler, OpenAiCompatibleLlm } from '../dist/index.js';

const paper = {
  id: 'paper-1',
  title: 'Curvature and systemic fragility',
  authors: [],
  abstract: 'We study network curvature and systemic fragility.',
  access: 'abstract_only',
  domain: 'physics',
  subjects: [],
  source: { provider: 'test', sourceId: '1' },
  ingestedAt: new Date().toISOString(),
};

test('OpenAI-compatible adapter and LLM compiler parse strict JSON', async () => {
  let called = false;
  const fetchImpl = async (input, init) => {
    called = true;
    assert.equal(String(input), 'http://localhost:11434/v1/chat/completions');
    const request = JSON.parse(String(init.body));
    assert.equal(request.model, 'research-model');
    assert.equal(request.response_format.type, 'json_object');
    return new Response(JSON.stringify({
      model: 'research-model',
      choices: [{ message: { content: JSON.stringify({
        problem: 'Measure systemic fragility',
        hypotheses: ['Curvature changes before stress'],
        assumptions: ['Graph construction is stable'],
        claims: ['Curvature is informative'],
        limitations: ['Small sample'],
        equations: [{ raw: 'R = f(G)', variables: ['R', 'G'], operators: ['='], confidence: 0.8 }],
        mechanisms: [{ mechanism: 'network', weight: 0.95, evidence: ['network curvature'] }],
        methods: ['graph geometry'],
        datasets: ['equity returns'],
        quantTranslation: 'Treat curvature as a network-state feature.',
        transferIdeas: ['Test curvature before bubble transitions'],
        confidence: 0.82
      }) } }]
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };

  const llm = new OpenAiCompatibleLlm({ baseUrl: 'http://localhost:11434', model: 'research-model', fetchImpl });
  const compiler = new LlmScientificCompiler(llm);
  const analysis = await compiler.compile(paper);
  assert.equal(called, true);
  assert.equal(analysis.problem, 'Measure systemic fragility');
  assert.equal(analysis.mechanisms[0].mechanism, 'network');
  assert.equal(analysis.confidence, 0.82);
});

test('LLM compiler fails closed on non-JSON output', async () => {
  const llm = { id: 'bad-llm', async complete() { return { text: 'I cannot provide JSON today.', provider: 'bad', model: 'bad' }; } };
  const compiler = new LlmScientificCompiler(llm);
  await assert.rejects(() => compiler.compile(paper), /JSON object/i);
});
