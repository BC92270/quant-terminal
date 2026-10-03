import type { EquationObject, ScientificAnalysis, ScientificPaper } from '../domain/types.js';
import { detectMechanisms } from '../ontology/mechanisms.js';
import { createId } from '../utils/id.js';
import { clamp, splitSentences, uniqueStrings } from '../utils/text.js';
import type { ScientificCompiler } from './types.js';

const CLAIM_MARKERS = /\b(we show|we find|we demonstrate|we establish|results show|our results|we prove|we propose|we introduce)\b/i;
const ASSUMPTION_MARKERS = /\b(we assume|assuming|under the assumption|subject to|provided that|suppose that)\b/i;
const LIMITATION_MARKERS = /\b(limitations?|however|caveat|future work|remains unclear|not address|cannot|restricted to)\b/i;
const METHOD_MARKERS = /\b(method|algorithm|model|estimator|simulation|monte carlo|regression|neural network|optimization|solver|experiment)\b/i;
const DATA_MARKERS = /\b(dataset|data set|sample|observations|s&p|spx|nasdaq|stoxx|futures|options|returns|prices|survey|cohort)\b/i;

function extractEquations(text: string): EquationObject[] {
  const patterns = [
    /\$\$([\s\S]{2,500}?)\$\$/g,
    /\\\[([\s\S]{2,500}?)\\\]/g,
    /\\\(([\s\S]{2,300}?)\\\)/g,
  ];
  const found: string[] = [];
  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) {
      const raw = match[1]?.trim();
      if (raw) found.push(raw);
    }
  }
  return uniqueStrings(found).slice(0, 30).map((raw) => ({
    raw,
    variables: uniqueStrings(raw.match(/[A-Za-z][A-Za-z0-9_]{0,12}/g) ?? []).slice(0, 30),
    operators: uniqueStrings(raw.match(/\\(?:sum|int|partial|nabla|frac|sqrt|log|exp)|[+\-*/=<>^]/g) ?? []).slice(0, 20),
    confidence: 0.7,
  }));
}

function firstUseful(sentences: readonly string[], fallback: string): string {
  return sentences.find((sentence) => sentence.length >= 40) ?? fallback;
}

function filtered(sentences: readonly string[], marker: RegExp, max = 8): string[] {
  return sentences.filter((sentence) => marker.test(sentence)).slice(0, max);
}

export class DeterministicScientificCompiler implements ScientificCompiler {
  public readonly id = 'deterministic-v1';

  public async compile(paper: ScientificPaper, _signal?: AbortSignal): Promise<ScientificAnalysis> {
    const text = [paper.title, paper.abstract, paper.fullText].filter(Boolean).join('\n\n');
    const sentences = splitSentences(text);
    const claims = filtered(sentences, CLAIM_MARKERS);
    const assumptions = filtered(sentences, ASSUMPTION_MARKERS);
    const limitations = filtered(sentences, LIMITATION_MARKERS);
    const methods = filtered(sentences, METHOD_MARKERS).map((sentence) => sentence.slice(0, 280));
    const datasets = filtered(sentences, DATA_MARKERS).map((sentence) => sentence.slice(0, 280));
    const mechanisms = detectMechanisms(text);
    const problem = firstUseful(sentences, paper.title);
    const confidence = clamp(0.25 + (paper.abstract ? 0.2 : 0) + (paper.fullText ? 0.35 : 0) + Math.min(0.15, mechanisms.length * 0.02));

    return {
      id: createId('analysis'),
      paperId: paper.id,
      compiledAt: new Date().toISOString(),
      problem,
      hypotheses: [],
      assumptions,
      claims,
      limitations,
      equations: extractEquations(text),
      mechanisms,
      methods: uniqueStrings(methods),
      datasets: uniqueStrings(datasets),
      quantTranslation: `Deterministic first-pass extraction for “${paper.title}”. Use an LLM compiler for a deeper formal and cross-domain interpretation.`,
      transferIdeas: [],
      confidence,
      compiler: this.id,
    };
  }
}
