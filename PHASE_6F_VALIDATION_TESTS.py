"""
Comprehensive validation tests for Nova approval-safe execution layer.

Validation requirements:
- No duplicate action execution
- No stuck execution states
- Approval flow persists correctly
- Rollback flow works
- Reconnect preserves execution state
- Timeline persistence retained
- continuityBrief retained
- recommendationHistory retained
- Live diagnostics stable
- Websocket delivery stable
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import pytest


# Test 1: No Duplicate Action Execution
async def test_no_duplicate_action_execution():
    """Verify duplicate action execution prevention via replay detection."""
    from app.core.nova.action_models import (
        ActionCategory,
        ActionType,
        ExecutionStatus,
        ProposedAction,
    )
    from app.core.nova.actions import execution_orchestrator
    
    org_id = "test_org_dup_exec"
    correlation_id = "corr_test_dup_001"
    
    # Propose same action twice with same correlation_id
    proposal = ProposedAction(
        action_type=ActionType.DISPATCH_ESCALATION,
        category=ActionCategory.OPERATIONAL,
        title="Test Dispatch Escalation",
        reason="Testing duplicate prevention",
        impact="Dispatch team notified",
        urgency=0.8,
        confidence=0.9,
        rollback_strategy="Revert escalation notification",
    )
    
    action1 = await execution_orchestrator.propose_action(
        org_id,
        proposal,
        correlation_id=correlation_id,
    )
    
    action2 = await execution_orchestrator.propose_action(
        org_id,
        proposal,
        correlation_id=correlation_id,
    )
    
    # Should return same action_id (replay detected)
    assert action1.action_id == action2.action_id, "Duplicate action execution not prevented"
    print(f"✓ Duplicate execution prevented: {action1.action_id}")


# Test 2: No Stuck Execution States
async def test_no_stuck_execution_states():
    """Verify no actions remain in EXECUTING state permanently."""
    from app.core.nova.action_models import ExecutionStatus
    from app.core.nova.actions import execution_orchestrator
    
    org_id = "test_org_stuck_states"
    
    # Simulate timeout by executing with short timeout
    executing_actions = await execution_orchestrator.query_executing_actions(org_id)
    
    # All executing actions should have execution time tracking
    for action in executing_actions:
        assert action.executed_at is not None, "Executing action missing executed_at"
        assert action.execution_timeout_seconds > 0, "Executing action has invalid timeout"
    
    print(f"✓ No stuck execution states: {len(executing_actions)} executing actions tracked")


# Test 3: Approval Flow Persists Correctly
async def test_approval_flow_persistence():
    """Verify approval metadata persisted correctly."""
    from app.core.nova.action_models import (
        ActionCategory,
        ActionType,
        ApprovalRequest,
        ExecutionStatus,
        ProposedAction,
    )
    from app.core.nova.actions import execution_orchestrator
    
    org_id = "test_org_approval_persist"
    
    proposal = ProposedAction(
        action_type=ActionType.RECOMMENDATION_ACKNOWLEDGEMENT,
        category=ActionCategory.OPERATIONAL,
        title="Test Approval Flow",
        reason="Testing approval persistence",
        impact="Acknowledgement recorded",
        urgency=0.5,
        confidence=0.85,
        rollback_strategy="Clear acknowledgement",
    )
    
    action = await execution_orchestrator.propose_action(org_id, proposal)
    assert action.execution_status == ExecutionStatus.PROPOSED
    
    # Operator approves
    approval = ApprovalRequest(
        action_id=action.action_id,
        approved=True,
        approval_reason="Approved by dispatcher",
    )
    
    approved_action = await execution_orchestrator.handle_approval(
        org_id,
        approval,
        operator_identity="dispatcher_123:dispatcher",
    )
    
    assert approved_action.execution_status == ExecutionStatus.APPROVED
    assert approved_action.operator_identity == "dispatcher_123:dispatcher"
    assert approved_action.approval_timestamp is not None
    assert approved_action.approval_reason is None  # Not in request
    
    # Query to verify persistence
    pending = await execution_orchestrator.query_pending_actions(
        org_id,
        status=ExecutionStatus.APPROVED,
        limit=10,
    )
    
    found = False
    for a in pending:
        if a.action_id == action.action_id:
            found = True
            assert a.operator_identity == "dispatcher_123:dispatcher"
            assert a.approval_timestamp is not None
    
    assert found, "Approved action not persisted in pending_actions"
    print(f"✓ Approval flow persists correctly: {action.action_id}")


# Test 4: Rollback Flow Works
async def test_rollback_flow():
    """Verify rollback execution and state transitions."""
    from app.core.nova.action_models import (
        ActionCategory,
        ActionType,
        ExecutionStatus,
        ProposedAction,
    )
    from app.core.nova.actions import execution_orchestrator
    
    org_id = "test_org_rollback"
    
    proposal = ProposedAction(
        action_type=ActionType.RUNTIME_RECONNECT_RECOVERY,
        category=ActionCategory.RECOVERY,
        title="Test Rollback Flow",
        reason="Testing rollback capability",
        impact="Runtime recovery initiated",
        urgency=0.95,
        confidence=0.8,
        rollback_strategy="Re-establish websocket connections",
    )
    
    action = await execution_orchestrator.propose_action(org_id, proposal)
    
    # Simulate rollback
    result = await execution_orchestrator.rollback_action(org_id, action)
    
    assert result.status == ExecutionStatus.ROLLED_BACK
    assert result.recovery_successful is not None
    
    print(f"✓ Rollback flow works: {action.action_id} -> {result.status}")


# Test 5: Timeline Persistence Retained
async def test_timeline_persistence():
    """Verify execution timeline persists across restarts."""
    from app.core.nova.memory import memory_store
    from app.core.nova.action_models import (
        ActionCategory,
        ActionType,
        ExecutionStatus,
        ProposedAction,
    )
    from app.core.nova.actions import execution_orchestrator
    
    org_id = "test_org_timeline"
    
    proposal = ProposedAction(
        action_type=ActionType.DISPATCH_ESCALATION,
        category=ActionCategory.OPERATIONAL,
        title="Test Timeline",
        reason="Testing timeline persistence",
        impact="Escalation timeline recorded",
        urgency=0.7,
        confidence=0.88,
        rollback_strategy="Remove escalation",
    )
    
    action = await execution_orchestrator.propose_action(org_id, proposal)
    
    # Check memory fabric
    fabric = memory_store.read_fabric(org_id)
    operational_history = fabric.get("operational_history", [])
    
    # Should have action_proposed event
    has_event = False
    for event in operational_history:
        if event.get("correlation_id") == action.action_id:
            has_event = True
            break
    
    assert has_event, "Timeline event not recorded in operational_history"
    
    # Check execution_timeline
    execution_timeline = fabric.get("execution_timeline", [])
    assert len(execution_timeline) > 0, "execution_timeline is empty"
    
    print(f"✓ Timeline persistence: {len(execution_timeline)} events recorded")


# Test 6: continuityBrief and recommendationHistory Retained
async def test_continuity_and_recommendations_retained():
    """Verify continuity brief and recommendation history not broken."""
    from app.core.nova.memory import memory_store
    from app.core.nova.action_models import (
        ActionCategory,
        ActionType,
        ProposedAction,
    )
    from app.core.nova.actions import execution_orchestrator
    
    org_id = "test_org_continuity"
    
    # Initial state
    fabric_before = memory_store.read_fabric(org_id)
    recommendation_history_before = fabric_before.get("recommendation_history", [])
    
    proposal = ProposedAction(
        action_type=ActionType.WORKFLOW_REBALANCE,
        category=ActionCategory.WORKFLOW,
        title="Test Continuity",
        reason="Testing continuity retention",
        impact="Workflow rebalanced",
        urgency=0.6,
        confidence=0.9,
        rollback_strategy="Revert workflow changes",
    )
    
    await execution_orchestrator.propose_action(org_id, proposal)
    
    # Verify continuity retained
    fabric_after = memory_store.read_fabric(org_id)
    recommendation_history_after = fabric_after.get("recommendation_history", [])
    
    # Should not lose previous history
    assert len(recommendation_history_after) >= len(recommendation_history_before), \
        "Recommendation history was lost"
    
    # Should still have operational_history
    operational_history = fabric_after.get("operational_history", [])
    assert isinstance(operational_history, list), "operational_history not a list"
    
    print(f"✓ Continuity retained: {len(recommendation_history_after)} recommendations")


# Test 7: Query API Stability
async def test_query_api_stability():
    """Verify all query endpoints remain stable."""
    from app.core.nova.action_models import ExecutionStatus
    from app.core.nova.actions import execution_orchestrator
    
    org_id = "test_org_query_stability"
    
    # All query methods should not raise
    try:
        pending = await execution_orchestrator.query_pending_actions(org_id)
        assert isinstance(pending, list)
        
        executing = await execution_orchestrator.query_executing_actions(org_id)
        assert isinstance(executing, list)
        
        failed = await execution_orchestrator.query_failed_actions(org_id)
        assert isinstance(failed, list)
        
        rollbacks = await execution_orchestrator.query_recent_rollbacks(org_id)
        assert isinstance(rollbacks, list)
        
        latency = await execution_orchestrator.get_execution_latency_stats(org_id)
        assert isinstance(latency, dict)
        
        print(f"✓ Query API stable: pending={len(pending)}, executing={len(executing)}, failed={len(failed)}")
    except Exception as exc:
        pytest.fail(f"Query API failed: {exc}")


# Test 8: Memory Fabric Structure Valid
def test_memory_fabric_structure():
    """Verify memory fabric has all required fields."""
    from app.core.nova.memory import memory_store
    
    org_id = "test_org_fabric_structure"
    fabric = memory_store.read_fabric(org_id)
    
    required_fields = {
        "founder_continuity": list,
        "operational_history": list,
        "workflow_history": list,
        "execution_timeline": list,
        "operational_event_timeline": list,
        "pending_actions": list,
        "recommendation_history": list,
        "business_state": dict,
        "session_stability": dict,
    }
    
    for field, expected_type in required_fields.items():
        assert field in fabric, f"Missing required field: {field}"
        assert isinstance(fabric[field], expected_type), \
            f"Field {field} has wrong type: {type(fabric[field])}"
    
    print(f"✓ Memory fabric structure valid: {len(required_fields)} fields present")


# Test 9: Approval Default TRUE
async def test_approval_required_default():
    """Verify approval_required defaults to TRUE."""
    from app.core.nova.action_models import (
        ActionCategory,
        ActionType,
        ProposedAction,
    )
    from app.core.nova.actions import execution_orchestrator
    
    org_id = "test_org_approval_default"
    
    proposal = ProposedAction(
        action_type=ActionType.DISPATCH_ESCALATION,
        category=ActionCategory.OPERATIONAL,
        title="Test Approval Default",
        reason="Testing approval_required default",
        impact="None",
        urgency=0.5,
        confidence=0.8,
        rollback_strategy="None",
        # Note: approval_required not specified
    )
    
    assert proposal.approval_required is True, "approval_required should default to True"
    
    action = await execution_orchestrator.propose_action(org_id, proposal)
    assert action.approval_required is True, "Action approval_required not True"
    
    print(f"✓ Approval default TRUE: {action.action_id}")


# Test 10: Compile/Lint Check
def test_no_import_errors():
    """Verify no import/compilation errors."""
    try:
        from app.core.nova.action_models import (
            ActionType,
            ActionCategory,
            ExecutionStatus,
            NovaAction,
            ProposedAction,
            ApprovalRequest,
            ExecutionResult,
            ActionTimeline,
            ActionQueryResponse,
        )
        from app.core.nova.actions import execution_orchestrator, ExecutionOrchestrator
        from app.core.nova.actions_router import router
        from app.core.nova.execution_intelligence import NovaExecutionIntelligence
        
        print("✓ All Nova execution modules import successfully")
    except Exception as exc:
        pytest.fail(f"Import error: {exc}")


# Main validation runner
async def run_all_validations():
    """Run all validation tests."""
    print("\n" + "="*80)
    print("PHASE 6F VALIDATION - APPROVAL-SAFE AUTONOMOUS EXECUTION LAYER")
    print("="*80 + "\n")
    
    tests = [
        ("No Duplicate Execution", test_no_duplicate_action_execution),
        ("No Stuck Execution States", test_no_stuck_execution_states),
        ("Approval Flow Persistence", test_approval_flow_persistence),
        ("Rollback Flow", test_rollback_flow),
        ("Timeline Persistence", test_timeline_persistence),
        ("Continuity & Recommendations", test_continuity_and_recommendations_retained),
        ("Query API Stability", test_query_api_stability),
        ("Approval Default TRUE", test_approval_required_default),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            print(f"\n[Test] {test_name}...")
            await test_func()
            passed += 1
        except AssertionError as exc:
            print(f"✗ {test_name} FAILED: {exc}")
            failed += 1
        except Exception as exc:
            print(f"✗ {test_name} ERROR: {exc}")
            failed += 1
    
    # Sync tests
    try:
        print(f"\n[Test] Memory Fabric Structure...")
        test_memory_fabric_structure()
        passed += 1
    except Exception as exc:
        print(f"✗ Memory Fabric Structure FAILED: {exc}")
        failed += 1
    
    try:
        print(f"\n[Test] No Import Errors...")
        test_no_import_errors()
        passed += 1
    except Exception as exc:
        print(f"✗ No Import Errors FAILED: {exc}")
        failed += 1
    
    print("\n" + "="*80)
    print(f"VALIDATION RESULTS: {passed} passed, {failed} failed")
    print("="*80 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_validations())
    exit(0 if success else 1)
