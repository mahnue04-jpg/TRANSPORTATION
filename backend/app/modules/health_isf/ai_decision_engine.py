"""Central AI decision engine with deterministic, auditable output contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class AIDecisionEngine:
    @staticmethod
    def _stable_id(material: dict[str, Any]) -> str:
        payload = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
        return f"dec_{digest}"

    @classmethod
    def build_decision(
        cls,
        *,
        organization_id: str,
        incidents: list[dict[str, Any]],
        predictions: list[dict[str, Any]],
        telemetry: dict[str, Any],
        candidate_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        high_incidents = [i for i in incidents if str(i.get("severity", "")).lower() == "high"]
        prediction_risk = sum(float(item.get("risk_score") or 0.0) for item in predictions) / max(len(predictions), 1)
        incident_risk = min(1.0, len(high_incidents) / 5.0)
        ws_risk = min(1.0, float((telemetry.get("websocket") or {}).get("disconnects_last_5m") or 0) / 10.0)

        total_risk = round(min(1.0, prediction_risk * 0.45 + incident_risk * 0.4 + ws_risk * 0.15), 4)
        confidence = round(max(0.05, 1.0 - total_risk * 0.65), 4)

        if total_risk >= 0.75:
            decision_type = "escalation_and_recovery"
            risk_level = "critical"
            requires_human_approval = True
        elif total_risk >= 0.5:
            decision_type = "autonomous_rebalancing"
            risk_level = "high"
            requires_human_approval = False
        elif total_risk >= 0.3:
            decision_type = "preventive_optimization"
            risk_level = "medium"
            requires_human_approval = False
        else:
            decision_type = "monitor_and_optimize"
            risk_level = "low"
            requires_human_approval = False

        sorted_actions = sorted(
            candidate_actions,
            key=lambda action: (
                0 if action.get("action_type") == "run_recovery" else 1,
                str(action.get("action_type") or ""),
            ),
        )
        recommended_actions = [
            {
                "action_type": item.get("action_type"),
                "parameters": item.get("parameters") or {},
                "priority": index + 1,
            }
            for index, item in enumerate(sorted_actions[:6])
        ]

        reasoning_summary = (
            f"Decision synthesized from {len(incidents)} incident signal(s), "
            f"{len(predictions)} predictive signal(s), and websocket risk {ws_risk:.2f}."
        )

        trace_material = {
            "organization_id": organization_id,
            "decision_type": decision_type,
            "risk_level": risk_level,
            "total_risk": total_risk,
            "recommended_actions": recommended_actions,
        }

        return {
            "decision_id": cls._stable_id(trace_material),
            "decision_type": decision_type,
            "confidence": confidence,
            "risk_level": risk_level,
            "recommended_actions": recommended_actions,
            "reasoning_summary": reasoning_summary,
            "requires_human_approval": requires_human_approval,
            "decision_trace": {
                "risk_components": {
                    "prediction_risk": round(prediction_risk, 4),
                    "incident_risk": round(incident_risk, 4),
                    "websocket_risk": round(ws_risk, 4),
                    "total_risk": total_risk,
                },
                "inputs": {
                    "incident_count": len(incidents),
                    "high_incident_count": len(high_incidents),
                    "prediction_count": len(predictions),
                },
                "replay_safe_key": cls._stable_id({
                    "organization_id": organization_id,
                    "decision_type": decision_type,
                    "recommended_actions": recommended_actions,
                }),
            },
        }
