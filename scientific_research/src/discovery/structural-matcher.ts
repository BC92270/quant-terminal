import type { ScientificAnalysis, StructuralMatch, TargetProblem } from '../domain/types.js';
import { clamp, uniqueStrings } from '../utils/text.js';

function normalize(value: string): string {
  return value.trim().toLowerCase().replace(/[\s-]+/g, '_');
}

export class StructuralMatcher {
  public match(analysis: ScientificAnalysis, target: TargetProblem): StructuralMatch {
    const sourceWeights = new Map(analysis.mechanisms.map((item) => [normalize(item.mechanism), item.weight]));
    const targetMechanisms = uniqueStrings(target.mechanisms.map(normalize));
    const overlap = targetMechanisms.filter((mechanism) => sourceWeights.has(mechanism));
    const missing = targetMechanisms.filter((mechanism) => !sourceWeights.has(mechanism));
    const sourceOnly = [...sourceWeights.keys()].filter((mechanism) => !targetMechanisms.includes(mechanism));
    const denominator = Math.max(1, new Set([...sourceWeights.keys(), ...targetMechanisms]).size);
    const weightedOverlap = overlap.reduce((sum, mechanism) => sum + (sourceWeights.get(mechanism) ?? 0), 0);
    const rawScore = weightedOverlap / denominator;
    const coverageBonus = targetMechanisms.length > 0 ? overlap.length / targetMechanisms.length * 0.25 : 0;
    const score = clamp(rawScore + coverageBonus);
    const rationale = overlap.map((mechanism) => `Shared mechanism: ${mechanism.replace(/_/g, ' ')}`);
    const warnings: string[] = [];
    if (overlap.length === 0) warnings.push('No explicit mechanism overlap. Treat any proposed relationship as analogy only.');
    if (analysis.confidence < 0.5) warnings.push('Source paper analysis confidence is low; acquire better text or use the LLM compiler before transfer.');
    if (targetMechanisms.length < 2) warnings.push('Target problem has a weak mechanism specification. Add mechanisms before interpreting the score.');

    return {
      sourcePaperId: analysis.paperId,
      targetProblemId: target.id,
      score,
      overlappingMechanisms: overlap,
      missingTargetMechanisms: missing,
      sourceOnlyMechanisms: sourceOnly,
      rationale,
      warnings,
    };
  }
}
