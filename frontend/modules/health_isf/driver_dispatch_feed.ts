/**
 * Driver dispatch recommendation feed transformation.
 * Recommendation-only outputs are preserved and surfaced with explainability.
 */

import type { DriverDispatchRecommendation, DriverDispatchSnapshot } from './driver_app_contracts';

export interface DriverDispatchFeedItem {
  recommendationId: string;
  rideId: string;
  recommendationType: string;
  targetId: string;
  confidence: number;
  explainability: string[];
  slaImpact: 'low' | 'medium' | 'high';
  emergencyPriority: boolean;
  approvalRequired: boolean;
  recommendationOnly: boolean;
}

function getSlaImpact(confidence: number, recommendationType: string): 'low' | 'medium' | 'high' {
  if (recommendationType.includes('emergency') || confidence >= 0.9) {
    return 'high';
  }
  if (confidence >= 0.7) {
    return 'medium';
  }
  return 'low';
}

export function buildDriverDispatchFeed(
  snapshot: DriverDispatchSnapshot | null | undefined,
): DriverDispatchFeedItem[] {
  if (!snapshot || !Array.isArray(snapshot.recommendations)) {
    return [];
  }

  const recommendationOnly = Boolean(snapshot.recommendation_only && !snapshot.unrestricted_execution);

  return snapshot.recommendations
    .filter((item: DriverDispatchRecommendation) => item.execution_mode === 'recommendation_only')
    .map((item: DriverDispatchRecommendation) => ({
      recommendationId: item.recommendation_id,
      rideId: item.ride_id,
      recommendationType: item.recommendation_type,
      targetId: item.target_id,
      confidence: Number(item.confidence || 0),
      explainability: Array.isArray(item.explainability) ? item.explainability : [],
      slaImpact: getSlaImpact(Number(item.confidence || 0), item.recommendation_type),
      emergencyPriority: item.recommendation_type.includes('emergency'),
      approvalRequired: Boolean(item.approval_required),
      recommendationOnly,
    }))
    .sort((a, b) => b.confidence - a.confidence);
}
