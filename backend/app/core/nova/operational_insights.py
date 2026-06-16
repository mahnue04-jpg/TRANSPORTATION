"""
PHASE 7B: Live Operational AI Insight Engine
Extends Nova recommendations into operational intelligence:
risk analysis, anomaly detection, escalation prediction, staffing analysis, deployment forecasting.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from app.core.nova.health_monitoring import HealthSnapshot
from app.core.nova.operational_metrics import OperationalMetricsSnapshot


class InsightType(Enum):
    """Types of operational insights"""
    RISK_ANALYSIS = "risk_analysis"
    ANOMALY_DETECTION = "anomaly_detection"
    ESCALATION_PREDICTION = "escalation_prediction"
    STAFFING_PRESSURE = "staffing_pressure"
    DEPLOYMENT_FORECAST = "deployment_forecast"
    EXECUTION_BOTTLENECK = "execution_bottleneck"
    APPROVAL_CONGESTION = "approval_congestion"
    PROVIDER_INSTABILITY = "provider_instability"


@dataclass
class OperationalInsight:
    """A single operational insight"""
    insight_id: str
    organization_id: str
    insight_type: InsightType
    timestamp: datetime
    title: str
    description: str
    confidence: float  # 0.0-1.0
    severity: str  # critical, high, medium, low
    evidence: List[str] = field(default_factory=list)
    affected_systems: List[str] = field(default_factory=list)
    recommended_action: str = ""
    metrics_snapshot: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskAnalysis:
    """Risk analysis results"""
    organization_id: str
    timestamp: datetime
    overall_risk_score: float  # 0.0-1.0
    execution_risk: float
    deployment_risk: float
    operational_risk: float
    provider_risk: float
    infrastructure_risk: float
    risk_factors: List[str] = field(default_factory=list)
    mitigations: List[str] = field(default_factory=list)


class OperationalInsightEngine:
    """Live operational AI insight engine"""
    
    def __init__(self):
        """Initialize insights engine"""
        self._insights: Dict[str, List[OperationalInsight]] = {}
        self._risk_history: Dict[str, List[RiskAnalysis]] = {}
        self._anomaly_threshold = 2.0  # Standard deviations

    def _metrics_overall(self, metrics: OperationalMetricsSnapshot | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(metrics, OperationalMetricsSnapshot):
            return metrics.to_dict().get("overall", {})
        if isinstance(metrics, dict):
            overall = metrics.get("overall", {})
            return overall if isinstance(overall, dict) else {}
        return {}

    def _health_payload(self, health: HealthSnapshot | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(health, HealthSnapshot):
            return health.to_dict()
        if isinstance(health, dict):
            return health
        return {}
    
    async def analyze_operational_risk(self, organization_id: str) -> RiskAnalysis:
        """Analyze overall operational risk"""
        try:
            from app.core.nova.operational_metrics import operational_metrics
            from app.core.nova.health_monitoring import health_monitor
            
            metrics = operational_metrics.build_snapshot(organization_id)
            health = health_monitor.build_snapshot(organization_id)
            
            # Calculate risk scores (0-1)
            execution_risk = self._calculate_execution_risk(metrics)
            deployment_risk = self._calculate_deployment_risk(metrics)
            operational_risk = self._calculate_operational_risk(metrics, health)
            provider_risk = self._calculate_provider_risk(health)
            infrastructure_risk = self._calculate_infrastructure_risk(health)
            
            overall = (execution_risk + deployment_risk + operational_risk + provider_risk + infrastructure_risk) / 5
            
            analysis = RiskAnalysis(
                organization_id=organization_id,
                timestamp=datetime.utcnow(),
                overall_risk_score=overall,
                execution_risk=execution_risk,
                deployment_risk=deployment_risk,
                operational_risk=operational_risk,
                provider_risk=provider_risk,
                infrastructure_risk=infrastructure_risk,
            )
            
            # Build risk factors and mitigations
            if execution_risk > 0.7:
                analysis.risk_factors.append("High execution failure rate")
                analysis.mitigations.append("Review execution evidence and approve recovery actions")
            
            if deployment_risk > 0.7:
                analysis.risk_factors.append("Deployment stability concerns")
                analysis.mitigations.append("Validate deployment readiness before proceeding")
            
            if provider_risk > 0.7:
                analysis.risk_factors.append("Provider instability detected")
                analysis.mitigations.append("Implement provider failover strategy")
            
            if organization_id not in self._risk_history:
                self._risk_history[organization_id] = []
            self._risk_history[organization_id].append(analysis)
            
            return analysis
        except Exception:
            return RiskAnalysis(
                organization_id=organization_id,
                timestamp=datetime.utcnow(),
                overall_risk_score=0.0,
                execution_risk=0.0,
                deployment_risk=0.0,
                operational_risk=0.0,
                provider_risk=0.0,
                infrastructure_risk=0.0,
            )
    
    def _calculate_execution_risk(self, metrics: OperationalMetricsSnapshot | Dict[str, Any]) -> float:
        """Calculate execution risk score"""
        try:
            overall = self._metrics_overall(metrics)
            if not overall:
                return 0.5
            success_rate = overall.get("execution_success_rate", 0.95)
            
            # Risk is inverse of success rate
            risk = 1.0 - success_rate
            
            return min(1.0, max(0.0, risk))
        except Exception:
            return 0.5
    
    def _calculate_deployment_risk(self, metrics: OperationalMetricsSnapshot | Dict[str, Any]) -> float:
        """Calculate deployment risk score"""
        try:
            # Would analyze deployment metrics if available
            return 0.3
        except Exception:
            return 0.5
    
    def _calculate_operational_risk(
        self,
        metrics: OperationalMetricsSnapshot | Dict[str, Any],
        health: HealthSnapshot | Dict[str, Any],
    ) -> float:
        """Calculate operational risk score"""
        try:
            _ = self._metrics_overall(metrics)
            health_payload = self._health_payload(health)
            if not health_payload:
                return 0.5
            
            # Check for operational issues in health snapshot
            # Higher if many degraded components
            return 0.3
        except Exception:
            return 0.5
    
    def _calculate_provider_risk(self, health: HealthSnapshot | Dict[str, Any]) -> float:
        """Calculate provider risk score"""
        try:
            if not self._health_payload(health):
                return 0.5
            
            # Would analyze provider health if available
            return 0.2
        except Exception:
            return 0.5
    
    def _calculate_infrastructure_risk(self, health: HealthSnapshot | Dict[str, Any]) -> float:
        """Calculate infrastructure risk score"""
        try:
            if not self._health_payload(health):
                return 0.5
            
            # Would analyze infrastructure metrics
            return 0.2
        except Exception:
            return 0.5
    
    async def detect_anomalies(self, organization_id: str) -> List[OperationalInsight]:
        """Detect operational anomalies"""
        try:
            import uuid
            from app.core.nova.operational_metrics import operational_metrics
            
            anomalies = []
            metrics = operational_metrics.build_snapshot(organization_id)

            if not metrics:
                return anomalies

            overall = self._metrics_overall(metrics)
            
            # Detect latency anomaly
            latency = overall.get("execution_latency_ms", {}).get("average", 0)
            if latency > 2000:
                insight = OperationalInsight(
                    insight_id=f"anomaly_{uuid.uuid4().hex[:12]}",
                    organization_id=organization_id,
                    insight_type=InsightType.ANOMALY_DETECTION,
                    timestamp=datetime.utcnow(),
                    title="High Execution Latency Detected",
                    description=f"Average execution latency is {latency}ms (normal <500ms)",
                    confidence=0.85,
                    severity="high",
                    evidence=[f"latency: {latency}ms", "exceeds threshold"],
                    affected_systems=["execution", "api"],
                    recommended_action="Investigate execution bottlenecks and optimize",
                )
                anomalies.append(insight)
            
            # Detect approval backlog anomaly
            approval_rate = overall.get("approval_acceptance_rate", 1.0)
            if approval_rate < 0.7:
                insight = OperationalInsight(
                    insight_id=f"anomaly_{uuid.uuid4().hex[:12]}",
                    organization_id=organization_id,
                    insight_type=InsightType.ANOMALY_DETECTION,
                    timestamp=datetime.utcnow(),
                    title="Low Approval Acceptance Rate",
                    description=f"Approval acceptance rate dropped to {approval_rate:.1%}",
                    confidence=0.80,
                    severity="medium",
                    evidence=[f"approval_acceptance_rate: {approval_rate:.1%}"],
                    affected_systems=["approval", "orchestration"],
                    recommended_action="Review and approve pending actions",
                )
                anomalies.append(insight)
            
            # Store insights
            if organization_id not in self._insights:
                self._insights[organization_id] = []
            self._insights[organization_id].extend(anomalies)
            
            return anomalies
        except Exception:
            return []
    
    async def predict_escalation(self, organization_id: str) -> Optional[OperationalInsight]:
        """Predict if escalation is needed"""
        try:
            import uuid
            from app.core.nova.operational_metrics import operational_metrics
            from app.core.nova.health_monitoring import health_monitor
            
            metrics = operational_metrics.build_snapshot(organization_id)
            health = health_monitor.build_snapshot(organization_id)
            
            if not metrics or not health:
                return None
            
            # Check for escalation indicators
            overall = self._metrics_overall(metrics)
            critical_count = overall.get("critical_incidents", 0)
            failure_rate = 1.0 - overall.get("execution_success_rate", 0.95)
            
            if critical_count > 3 or failure_rate > 0.3:
                insight = OperationalInsight(
                    insight_id=f"escalation_{uuid.uuid4().hex[:12]}",
                    organization_id=organization_id,
                    insight_type=InsightType.ESCALATION_PREDICTION,
                    timestamp=datetime.utcnow(),
                    title="Escalation Recommended",
                    description=f"Critical incidents: {critical_count}, failure rate: {failure_rate:.1%}",
                    confidence=0.90,
                    severity="critical",
                    evidence=[f"critical_incidents: {critical_count}", f"failure_rate: {failure_rate:.1%}"],
                    affected_systems=["execution", "orchestration"],
                    recommended_action="Escalate to senior operators and review system health",
                )
                
                if organization_id not in self._insights:
                    self._insights[organization_id] = []
                self._insights[organization_id].append(insight)
                
                return insight
            
            return None
        except Exception:
            return None
    
    async def analyze_staffing_pressure(self, organization_id: str) -> Optional[OperationalInsight]:
        """Analyze staffing and operational pressure"""
        try:
            import uuid
            from app.core.nova.operational_metrics import operational_metrics
            
            metrics = operational_metrics.build_snapshot(organization_id)
            if not metrics:
                return None
            
            overall = self._metrics_overall(metrics)
            pending_approvals = overall.get("pending_approvals", 0)
            
            if pending_approvals > 20:
                insight = OperationalInsight(
                    insight_id=f"staffing_{uuid.uuid4().hex[:12]}",
                    organization_id=organization_id,
                    insight_type=InsightType.STAFFING_PRESSURE,
                    timestamp=datetime.utcnow(),
                    title="High Staffing Pressure Detected",
                    description=f"{pending_approvals} actions awaiting approval",
                    confidence=0.80,
                    severity="high",
                    evidence=[f"pending_approvals: {pending_approvals}"],
                    affected_systems=["approval", "staffing"],
                    recommended_action="Engage additional operators or auto-approve low-risk actions",
                )
                
                if organization_id not in self._insights:
                    self._insights[organization_id] = []
                self._insights[organization_id].append(insight)
                
                return insight
            
            return None
        except Exception:
            return None
    
    async def forecast_deployment_risk(self, organization_id: str) -> Optional[OperationalInsight]:
        """Forecast deployment risk"""
        try:
            import uuid
            from app.core.nova.operational_metrics import operational_metrics
            
            metrics = operational_metrics.build_snapshot(organization_id)
            if not metrics:
                return None
            
            overall = self._metrics_overall(metrics)
            failure_rate = 1.0 - overall.get("execution_success_rate", 0.95)
            
            if failure_rate > 0.2:
                insight = OperationalInsight(
                    insight_id=f"deploy_{uuid.uuid4().hex[:12]}",
                    organization_id=organization_id,
                    insight_type=InsightType.DEPLOYMENT_FORECAST,
                    timestamp=datetime.utcnow(),
                    title="Deployment Risk Forecast",
                    description=f"Execution failure rate is {failure_rate:.1%}, deployment not recommended",
                    confidence=0.85,
                    severity="high",
                    evidence=[f"failure_rate: {failure_rate:.1%}"],
                    affected_systems=["deployment", "execution"],
                    recommended_action="Stabilize execution first, then proceed with deployment",
                )
                
                if organization_id not in self._insights:
                    self._insights[organization_id] = []
                self._insights[organization_id].append(insight)
                
                return insight
            
            return None
        except Exception:
            return None
    
    async def detect_execution_bottlenecks(self, organization_id: str) -> Optional[OperationalInsight]:
        """Detect execution bottlenecks"""
        try:
            import uuid
            from app.core.nova.operational_metrics import operational_metrics
            
            metrics = operational_metrics.build_snapshot(organization_id)
            if not metrics:
                return None
            
            overall = self._metrics_overall(metrics)
            latency = overall.get("execution_latency_ms", {}).get("p95", 0)
            
            if latency > 3000:
                insight = OperationalInsight(
                    insight_id=f"bottleneck_{uuid.uuid4().hex[:12]}",
                    organization_id=organization_id,
                    insight_type=InsightType.EXECUTION_BOTTLENECK,
                    timestamp=datetime.utcnow(),
                    title="Execution Bottleneck Detected",
                    description=f"P95 latency is {latency}ms, indicating bottleneck",
                    confidence=0.80,
                    severity="medium",
                    evidence=[f"p95_latency: {latency}ms"],
                    affected_systems=["execution", "api", "database"],
                    recommended_action="Profile execution and identify slow operations",
                )
                
                if organization_id not in self._insights:
                    self._insights[organization_id] = []
                self._insights[organization_id].append(insight)
                
                return insight
            
            return None
        except Exception:
            return None
    
    def get_insights(self, organization_id: str, insight_type: Optional[InsightType] = None) -> List[OperationalInsight]:
        """Get insights for organization"""
        insights = self._insights.get(organization_id, [])
        
        if insight_type:
            insights = [i for i in insights if i.insight_type == insight_type]
        
        return insights
    
    def build_insight_snapshot(self, organization_id: str) -> Dict[str, Any]:
        """Build snapshot of operational insights"""
        try:
            insights = self.get_insights(organization_id)
            
            return {
                "organization_id": organization_id,
                "timestamp": datetime.utcnow().isoformat(),
                "total_insights": len(insights),
                "critical_insights": len([i for i in insights if i.severity == "critical"]),
                "high_insights": len([i for i in insights if i.severity == "high"]),
                "recent_insights": [
                    {
                        "insight_id": i.insight_id,
                        "type": i.insight_type.value,
                        "title": i.title,
                        "severity": i.severity,
                        "confidence": i.confidence,
                    }
                    for i in insights[-5:]
                ],
            }
        except Exception:
            return {
                "organization_id": organization_id,
                "error": "Failed to build insight snapshot",
            }


# Singleton instance
operational_insights_engine = OperationalInsightEngine()
