import { describe, expect, it } from 'vitest';
import { analyzeFeatureDependencies } from '../../../scripts/check-feature-dependencies.mjs';

describe('feature dependency direction', () => {
  it('keeps the feature graph acyclic and explicitly allow-listed', () => {
    const report = analyzeFeatureDependencies();
    const edgeKeys = new Set(report.featureEdges.map((edge) => edge.key));

    expect(report.violations).toEqual([]);
    expect(report.cycles).toEqual([]);
    expect(report.selfBarrelImports).toEqual([]);
    expect(report.featureEdges.length).toBe(report.allowedFeatureEdges.length);
    expect(edgeKeys.has('environments -> settings')).toBe(false);
    expect(edgeKeys.has('settings -> environments')).toBe(true);
    expect(edgeKeys.has('tasks -> workspaces')).toBe(false);
    expect(edgeKeys.has('workspaces -> tasks')).toBe(false);
  });
});
