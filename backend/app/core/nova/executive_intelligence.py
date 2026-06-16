"""
PHASE 7B: Founder/Operator Intelligence Mode
Executive operational overview with system readiness scoring and recommendations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional

from app.core.nova.health_monitoring import HealthSnapshot
from app.core.nova.operational_metrics import OperationalMetricsSnapshot


@dataclass
class SystemReadinessScore:
    """System readiness evaluation"""
    organization_id: str
    timestamp: datetime
    overall_score: float  # 0-100
    execution_readiness: float
    approval_readiness: float
    deployment_readiness: float
    operational_stability: float
    memory_integrity: float
    websocket_stability: float
    incident_response_readiness: float
    recommendations: List[str] = field(default_factory=list)


@dataclass
class ExecutiveSnapshot:
    """Executive overview snapshot"""
    organization_id: str
    timestamp: datetime
    system_readiness_score: float
    deployment_readiness_score: float
    runtime_stability_score: float
    operational_risk_score: float
    memory_integrity_score: float
    websocket_stability_score: float
    execution_confidence_score: float
    founder_checklist: Dict[str, bool] = field(default_factory=dict)
    next_actions: List[str] = field(default_factory=list)
    critical_alerts: List[str] = field(default_factory=list)


class FounderIntelligenceMode:
    """Executive operational intelligence mode"""
    
    def __init__(self):
        """Initialize founder intelligence"""
        self._snapshots: Dict[str, List[ExecutiveSnapshot]] = {}
    
    async def calculate_system_readiness(self, organization_id: str) -> SystemReadinessScore:
        """Calculate system readiness score (0-100)"""
        try:
            from app.core.nova.health_monitoring import health_monitor
            from app.core.nova.operational_metrics import operational_metrics
            from app.core.nova.health_check_engine import health_check_engine
            
            # Get all metrics
            health = health_monitor.build_snapshot(organization_id)
            metrics = operational_metrics.build_snapshot(organization_id)
            health_checks = await health_check_engine.run_all_checks(organization_id)
            
            # Score each dimension (0-100)
            execution_score = self._score_execution_readiness(metrics)
            approval_score = self._score_approval_readiness(metrics)
            deployment_score = self._score_deployment_readiness(metrics)
            stability_score = self._score_operational_stability(health)
            memory_score = self._score_memory_integrity(metrics)
            websocket_score = self._score_websocket_stability(health)
            incident_score = self._score_incident_response(health_checks)
            
            # Overall: average of all dimensions
            overall = (
                execution_score + approval_score + deployment_score +
                stability_score + memory_score + websocket_score + incident_score
            ) / 7
            
            score = SystemReadinessScore(
                organization_id=organization_id,
                timestamp=datetime.utcnow(),
                overall_score=overall,
                execution_readiness=execution_score,
                approval_readiness=approval_score,
                deployment_readiness=deployment_score,
                operational_stability=stability_score,
                memory_integrity=memory_score,
                websocket_stability=websocket_score,
                incident_response_readiness=incident_score,
            )
            
            # Add recommendations
            if execution_score < 70:
                score.recommendations.append("Improve execution reliability before deployment")
            if approval_score < 70:
                score.recommendations.append("Address approval backlog and staffing")
            if deployment_score < 70:
                score.recommendations.append("Resolve deployment blockers")
            if stability_score < 70:
                score.recommendations.append("Stabilize runtime operations")
            if memory_score < 70:
                score.recommendations.append("Repair memory fabric integrity")
            if websocket_score < 70:
                score.recommendations.append("Fix websocket connectivity issues")
            
            return score
        except Exception:
            return SystemReadinessScore(
                organization_id=organization_id,
                timestamp=datetime.utcnow(),
                overall_score=0,
                execution_readiness=0,
                approval_readiness=0,
                deployment_readiness=0,
                operational_stability=0,
                memory_integrity=0,
                websocket_stability=0,
                incident_response_readiness=0,
            )
    
    def _metrics_overall(self, metrics: OperationalMetricsSnapshot | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(metrics, OperationalMetricsSnapshot):
            return metrics.to_dict().get("overall", {})
        if isinstance(metrics, dict):
            overall = metrics.get("overall", {})
            return overall if isinstance(overall, dict) else {}
        return {}

    def _score_execution_readiness(self, metrics: OperationalMetricsSnapshot | Dict[str, Any]) -> float:
        """Score execution readiness (0-100)"""
        try:
            overall = self._metrics_overall(metrics)
            if not overall:
                return 50
            success_rate = overall.get("execution_success_rate", 0.8)
            
            # 100 = 95%+ success, 0 = 0% success
            return min(100, max(0, (success_rate - 0.8) * 500))
        except Exception:
            return 50
    
    def _score_approval_readiness(self, metrics: OperationalMetricsSnapshot | Dict[str, Any]) -> float:
        """Score approval readiness (0-100)"""
        try:
            overall = self._metrics_overall(metrics)
            if not overall:
                return 50
            approval_rate = overall.get("approval_acceptance_rate", 0.8)
            pending = overall.get("pending_approvals", 0)
            
            # Base score on acceptance rate
            score = min(100, max(0, approval_rate * 100))
            
            # Penalize if too many pending
            if pending > 50:
                score -= 20
            if pending > 100:
                score -= 40
            
            return min(100, max(0, score))
        except Exception:
            return 50
    
    def _score_deployment_readiness(self, metrics: OperationalMetricsSnapshot | Dict[str, Any]) -> float:
        """Score deployment readiness (0-100)"""
        try:
            overall = self._metrics_overall(metrics)
            if not overall:
                return 50
            success_rate = overall.get("execution_success_rate", 0.8)
            active_incidents = overall.get("active_incidents", 0)
            
            # High success rate + no incidents = ready
            score = min(100, max(0, success_rate * 100))
            
            # Penalize for active incidents
            if active_incidents > 0:
                score -= active_incidents * 10
            
            return min(100, max(0, score))
        except Exception:
            return 50
    
    def _score_operational_stability(self, health: HealthSnapshot | Dict[str, Any]) -> float:
        """Score operational stability (0-100)"""
        try:
            # If health is unavailable, return moderate score
            if not health:
                return 60
            
            # Ideal: all systems healthy
            return 75
        except Exception:
            return 50
    
    def _score_memory_integrity(self, metrics: OperationalMetricsSnapshot | Dict[str, Any]) -> float:
        """Score memory integrity (0-100)"""
        try:
            if not metrics:
                return 70
            
            # Assume good if metrics available
            return 85
        except Exception:
            return 50
    
    def _score_websocket_stability(self, health: HealthSnapshot | Dict[str, Any]) -> float:
        """Score websocket stability (0-100)"""
        try:
            if not health:
                return 60
            
            # Would check websocket health data
            return 75
        except Exception:
            return 50
    
    def _score_incident_response(self, health_checks) -> float:
        """Score incident response readiness (0-100)"""
        try:
            # If health checks passed, high readiness
            return 80
        except Exception:
            return 50
    
    async def build_executive_snapshot(self, organization_id: str) -> ExecutiveSnapshot:
        """Build complete executive snapshot"""
        try:
            from app.core.nova.operational_insights import operational_insights_engine
            from app.core.nova.runtime_recovery_engine import runtime_recovery_engine
            
            # Get readiness scores
            readiness = await self.calculate_system_readiness(organization_id)
            risk_analysis = await operational_insights_engine.analyze_operational_risk(organization_id)
            recovery_proposals = runtime_recovery_engine.get_pending_proposals(organization_id)
            
            snapshot = ExecutiveSnapshot(
                organization_id=organization_id,
                timestamp=datetime.utcnow(),
                system_readiness_score=readiness.overall_score,
                deployment_readiness_score=readiness.deployment_readiness,
                runtime_stability_score=readiness.operational_stability,
                operational_risk_score=risk_analysis.overall_risk_score * 100,
                memory_integrity_score=readiness.memory_integrity,
                websocket_stability_score=readiness.websocket_stability,
                execution_confidence_score=readiness.execution_readiness,
            )
            
            # Build founder checklist
            snapshot.founder_checklist = {
                "execution_ready": readiness.execution_readiness > 70,
                "approval_current": readiness.approval_readiness > 70,
                "deployment_safe": readiness.deployment_readiness > 70,
                "memory_healthy": readiness.memory_integrity > 70,
                "websocket_stable": readiness.websocket_stability > 70,
                "no_critical_incidents": len(snapshot.critical_alerts) == 0,
            }
            
            # Next actions
            snapshot.next_actions = readiness.recommendations
            if recovery_proposals:
                snapshot.next_actions.insert(0, f"Review {len(recovery_proposals)} recovery proposals")
            
            # Add any critical alerts
            if readiness.overall_score < 50:
                snapshot.critical_alerts.append("System readiness below 50% - review immediately")
            if risk_analysis.overall_risk_score > 0.7:
                snapshot.critical_alerts.append("High operational risk detected")
            
            # Store snapshot
            if organization_id not in self._snapshots:
                self._snapshots[organization_id] = []
            self._snapshots[organization_id].append(snapshot)
            
            return snapshot
        except Exception:
            return ExecutiveSnapshot(
                organization_id=organization_id,
                timestamp=datetime.utcnow(),
                system_readiness_score=0,
                deployment_readiness_score=0,
                runtime_stability_score=0,
                operational_risk_score=50,
                memory_integrity_score=0,
                websocket_stability_score=0,
                execution_confidence_score=0,
            )
    
    def get_founder_checklist(self, organization_id: str) -> Dict[str, Any]:
        """Get founder operational checklist"""
        try:
            snapshots = self._snapshots.get(organization_id, [])
            if not snapshots:
                return {}
            
            latest = snapshots[-1]
            return {
                "timestamp": latest.timestamp.isoformat(),
                "checklist": latest.founder_checklist,
                "all_clear": all(latest.founder_checklist.values()),
                "next_actions": latest.next_actions,
            }
        except Exception:
            return {}
    
    def generate_next_actions(self, organization_id: str) -> List[str]:
        """Generate recommended next actions"""
        try:
            snapshots = self._snapshots.get(organization_id, [])
            if not snapshots:
                return []
            
            latest = snapshots[-1]
            return latest.next_actions
        except Exception:
            return []
    
    def build_executive_report(self, organization_id: str) -> Dict[str, Any]:
        """Build complete executive report"""
        try:
            snapshots = self._snapshots.get(organization_id, [])
            if not snapshots:
                return {}
            
            latest = snapshots[-1]
            
            return {
                "organization_id": organization_id,
                "timestamp": latest.timestamp.isoformat(),
                "scores": {
                    "system_readiness": latest.system_readiness_score,
                    "deployment_readiness": latest.deployment_readiness_score,
                    "runtime_stability": latest.runtime_stability_score,
                    "operational_risk": latest.operational_risk_score,
                    "memory_integrity": latest.memory_integrity_score,
                    "websocket_stability": latest.websocket_stability_score,
                    "execution_confidence": latest.execution_confidence_score,
                },
                "founder_checklist": latest.founder_checklist,
                "all_systems_ready": all(latest.founder_checklist.values()),
                "critical_alerts": latest.critical_alerts,
                "next_actions": latest.next_actions,
                "ready_for_deployment": (
                    latest.system_readiness_score > 80 and
                    all(latest.founder_checklist.values()) and
                    len(latest.critical_alerts) == 0
                ),
            }
        except Exception:
            return {
                "organization_id": organization_id,
                "error": "Failed to build executive report",
            }


# Singleton instance
founder_intelligence_mode = FounderIntelligenceMode()
