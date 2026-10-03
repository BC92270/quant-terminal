import type { ScientificDomain } from '../domain/types.js';
import { clamp, uniqueStrings } from '../utils/text.js';

export const MECHANISMS = [
  'adaptation',
  'attractor',
  'bifurcation',
  'cascade',
  'competition',
  'conservation',
  'criticality',
  'diffusion',
  'feedback',
  'instability',
  'mean_reversion',
  'multiscale',
  'network',
  'nonlinearity',
  'oscillation',
  'propagation',
  'selection',
  'self_organization',
  'synchronization',
  'threshold',
] as const;

export type Mechanism = (typeof MECHANISMS)[number];

const KEYWORDS: Record<Mechanism, readonly string[]> = {
  adaptation: ['adaptation', 'adaptive', 'learning dynamics', 'evolutionary response'],
  attractor: ['attractor', 'basin of attraction', 'fixed point', 'limit cycle'],
  bifurcation: ['bifurcation', 'tipping point', 'regime transition', 'phase transition'],
  cascade: ['cascade', 'avalanche', 'domino', 'chain reaction'],
  competition: ['competition', 'competitive', 'game theoretic', 'strategic interaction'],
  conservation: ['conservation', 'conserved quantity', 'invariant measure'],
  criticality: ['criticality', 'critical point', 'critical transition', 'susceptibility'],
  diffusion: ['diffusion', 'brownian', 'random walk', 'heat equation'],
  feedback: ['feedback', 'self-reinforcing', 'positive feedback', 'negative feedback'],
  instability: ['instability', 'unstable', 'loss of stability', 'fragility'],
  mean_reversion: ['mean reversion', 'mean-reverting', 'ornstein-uhlenbeck'],
  multiscale: ['multiscale', 'multi-scale', 'scale invariance', 'scaling law', 'fractal'],
  network: ['network', 'graph', 'nodes and edges', 'connectivity', 'centrality'],
  nonlinearity: ['nonlinear', 'non-linear', 'nonlinearity', 'non-linearity'],
  oscillation: ['oscillation', 'oscillatory', 'cycle', 'periodic'],
  propagation: ['propagation', 'transmission', 'spread', 'spillover'],
  selection: ['selection', 'survival', 'fitness', 'replicator dynamics'],
  self_organization: ['self-organization', 'self organization', 'emergent order'],
  synchronization: ['synchronization', 'synchronisation', 'phase locking', 'coherence'],
  threshold: ['threshold', 'critical boundary', 'trigger level', 'barrier'],
};

const DOMAIN_KEYWORDS: Array<[ScientificDomain, readonly string[]]> = [
  ['physics', ['physics', 'quantum', 'thermodynamic', 'relativity', 'fluid', 'particle', 'spin glass', 'statistical mechanics']],
  ['mathematics', ['theorem', 'lemma', 'topology', 'geometry', 'manifold', 'measure theory', 'functional analysis']],
  ['statistics', ['statistical', 'estimator', 'regression', 'bayesian', 'likelihood', 'inference']],
  ['computer_science', ['algorithm', 'neural network', 'machine learning', 'computer science', 'complexity']],
  ['biology', ['biological', 'ecology', 'epidemiology', 'evolutionary biology', 'genomic']],
  ['finance', ['financial market', 'asset pricing', 'portfolio', 'option pricing', 'volatility', 'market microstructure']],
  ['economics', ['economic', 'macroeconomic', 'microeconomic', 'econometric']],
  ['engineering', ['control system', 'engineering', 'signal processing', 'robotics']],
];

export function detectMechanisms(text: string): Array<{ mechanism: Mechanism; weight: number; evidence: string[] }> {
  const normalized = text.toLowerCase();
  const matches = MECHANISMS.map((mechanism) => {
    const evidence = KEYWORDS[mechanism].filter((keyword) => normalized.includes(keyword));
    const weight = clamp(evidence.length / Math.max(2, KEYWORDS[mechanism].length));
    return { mechanism, weight, evidence: uniqueStrings(evidence) };
  }).filter((item) => item.evidence.length > 0);

  return matches.sort((a, b) => b.weight - a.weight || a.mechanism.localeCompare(b.mechanism));
}

export function inferDomain(text: string): ScientificDomain {
  const normalized = text.toLowerCase();
  const scores = DOMAIN_KEYWORDS.map(([domain, keywords]) => ({
    domain,
    score: keywords.reduce((acc, keyword) => acc + (normalized.includes(keyword) ? 1 : 0), 0),
  })).sort((a, b) => b.score - a.score);

  const best = scores[0];
  if (!best || best.score === 0) return 'unknown';
  const second = scores[1];
  if (second && second.score === best.score) return 'multidisciplinary';
  return best.domain;
}
