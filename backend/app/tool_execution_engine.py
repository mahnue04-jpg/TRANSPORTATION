"""
Tool Execution Engine
====================

Orchestrates tool discovery, execution, and result handling.

Responsibilities:
- Detect executable actions from prompts
- Match intents to available tools
- Execute tools safely with fallback handling
- Compose multi-step workflows
- Return structured tool results
- Maintain execution telemetry
"""

import re
import asyncio
import time
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

from app.tool_registry import (
    ToolRegistry, 
    BaseTool, 
    ToolExecutionResult, 
    get_registry
)

logger = logging.getLogger(__name__)


# Action detection patterns
ACTION_VERBS = {
    'create': ['create', 'make', 'build', 'draft', 'generate', 'construct'],
    'plan': ['plan', 'outline', 'organize', 'prepare', 'schedule'],
    'research': ['research', 'investigate', 'analyze', 'study', 'explore', 'find'],
    'summarize': ['summarize', 'brief', 'overview', 'recap', 'condense'],
    'email': ['draft email', 'write email', 'compose email', 'prepare email'],
    'proposal': ['proposal', 'pitch', 'offer', 'bid'],
    'invoice': ['invoice', 'bill', 'payment'],
    'marketing': ['marketing', 'advertise', 'promote', 'campaign', 'social'],
    'business': ['business plan', 'startup', 'launch', 'company', 'venture', 'business', 'start'],
    'workflow': ['help me launch', 'launch my', 'run workflow', 'orchestrate'],
    'browser_open': ['open', 'visit', 'go to'],
    'memory_lookup': ['remember', 'what do you know about me', 'what do you remember'],
}


@dataclass
class DetectedAction:
    """Result of action detection."""
    action_type: str  # e.g., 'create', 'plan', 'research'
    confidence: float  # 0.0 - 1.0
    matched_pattern: str
    matching_tools: List[BaseTool]


@dataclass
class ExecutionContext:
    """Context passed to tools during execution."""
    message: str
    user_id: str
    memory_context: Optional[str] = None
    memory_preferences: Optional[Dict[str, Any]] = None
    tool_params: Optional[Dict[str, Any]] = None
    previous_results: Optional[Dict[str, Any]] = None  # For chained workflows


class ActionDetector:
    """
    Detects actionable intents from user prompts.
    
    Examples:
    - "Help me start a business" → action_type='business', confidence=0.9
    - "Create a proposal" → action_type='proposal', confidence=0.95
    - "Research CRM tools" → action_type='research', confidence=0.9
    """
    
    def __init__(self):
        self.logger = logging.getLogger("action_detector")
    
    def detect(self, message: str, registry: ToolRegistry) -> Optional[DetectedAction]:
        """
        Detect actionable intent from message.
        
        Returns:
            DetectedAction if action found, None otherwise
        """
        if not message or len(message) < 3:
            return None
        
        message_lower = message.lower()
        if re.search(r'https?://\S+|www\.\S+', message_lower):
            browser_tools = registry.find_matching_tools('browser_open')
            if browser_tools:
                return DetectedAction(
                    action_type='browser_open',
                    confidence=0.95,
                    matched_pattern='url_detected',
                    matching_tools=browser_tools,
                )
        best_match = None
        best_confidence = 0.0
        
        # Check each action type
        for action_type, patterns in ACTION_VERBS.items():
            for pattern in patterns:
                if pattern in message_lower:
                    # Calculate confidence based on:
                    # - Early appearance in message (higher = more confident)
                    # - Exact vs substring match
                    pos = message_lower.find(pattern)
                    position_score = 1.0 - (pos / len(message_lower) * 0.3)  # Max 30% penalty
                    
                    confidence = min(0.95, 0.7 + (position_score * 0.25))
                    
                    candidate_tools = registry.find_matching_tools(action_type)
                    if not candidate_tools:
                        continue
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = (action_type, pattern, candidate_tools)
        
        if best_match is None:
            return None
        
        action_type, pattern, matching_tools = best_match
        
        self.logger.info(
            f"Action detected: type={action_type}, confidence={best_confidence:.2f}, "
            f"matching_tools={len(matching_tools)}"
        )
        
        return DetectedAction(
            action_type=action_type,
            confidence=best_confidence,
            matched_pattern=pattern,
            matching_tools=matching_tools
        )


class ToolExecutionEngine:
    """
    Main orchestrator for tool execution.
    
    Handles:
    - Action detection
    - Tool matching
    - Safe execution
    - Fallback handling
    - Workflow composition
    """
    
    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or get_registry()
        self.detector = ActionDetector()
        self.logger = logging.getLogger("execution_engine")
    
    async def should_execute(self, message: str, intent: Optional[str] = None) -> bool:
        """
        Determine if message should trigger tool execution.
        
        Checks:
        - Action detection passes
        - Matching tools available
        - Not already a specialized query type
        """
        if not message or len(message) < 5:
            return False
        
        # Never execute if already routed (checked upstream)
        # This is a safety guard; actual routing takes precedence
        
        action = self.detector.detect(message, self.registry)
        return action is not None and len(action.matching_tools) > 0
    
    async def execute_primary_tool(
        self,
        message: str,
        user_id: str,
        memory_context: Optional[str] = None,
        memory_preferences: Optional[Dict[str, Any]] = None,
        tool_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a single tool for the given message.
        
        Args:
            message: user prompt
            user_id: user identifier
            memory_context: memory context if available
            memory_preferences: user preferences if available
            tool_id: specific tool to use (if not provided, best-match is selected)
        
        Returns:
            Tool result dict or None if execution skipped
        """
        try:
            # Detect action
            action = self.detector.detect(message, self.registry)
            if not action:
                return None
            
            # Select tool
            if tool_id:
                tool = self.registry.get_tool(tool_id)
                if not tool:
                    self.logger.warning(f"Tool {tool_id} not found")
                    return None
            else:
                # Use first matching tool
                if not action.matching_tools:
                    return None
                tool = action.matching_tools[0]
            
            # Build execution context
            context = ExecutionContext(
                message=message,
                user_id=user_id,
                memory_context=memory_context,
                memory_preferences=memory_preferences,
                tool_params={'action_type': action.action_type}
            )
            
            # Execute with timeout
            start_time = time.time()
            try:
                result = await asyncio.wait_for(
                    tool.execute(context.__dict__),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                self.logger.warning(f"Tool {tool.tool_id} timed out")
                result = ToolExecutionResult(
                    tool_id=tool.tool_id,
                    success=False,
                    error="Tool execution timed out",
                    fallback_used=True
                )
            
            execution_ms = int((time.time() - start_time) * 1000)
            result.execution_ms = execution_ms
            
            # Return structured result
            return {
                'tool_id': result.tool_id,
                'success': result.success,
                'data': result.data,
                'error': result.error,
                'fallback_used': result.fallback_used,
                'execution_ms': execution_ms,
                'action_type': action.action_type
            }
        
        except Exception as e:
            self.logger.error(f"Tool execution error: {str(e)}", exc_info=True)
            return None
    
    async def execute_workflow(
        self,
        workflow_steps: List[Dict[str, Any]],
        user_id: str,
        memory_context: Optional[str] = None,
        memory_preferences: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a multi-step workflow.
        
        Args:
            workflow_steps: List of {tool_id, message, params}
            user_id: user identifier
            memory_context: memory context
            memory_preferences: user preferences
        
        Returns:
            Aggregated workflow results
        """
        results = {}
        previous_results = {}
        
        try:
            for i, step in enumerate(workflow_steps):
                tool_id = step.get('tool_id')
                message = step.get('message', '')
                params = step.get('params', {})
                
                tool = self.registry.get_tool(tool_id)
                if not tool:
                    self.logger.warning(f"Workflow step {i}: tool {tool_id} not found")
                    continue
                
                context = ExecutionContext(
                    message=message,
                    user_id=user_id,
                    memory_context=memory_context,
                    memory_preferences=memory_preferences,
                    tool_params=params,
                    previous_results=previous_results
                )
                
                start_time = time.time()
                try:
                    result = await asyncio.wait_for(
                        tool.execute(context.__dict__),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    result = ToolExecutionResult(
                        tool_id=tool_id,
                        success=False,
                        error="Workflow step timed out",
                        fallback_used=True
                    )
                
                result.execution_ms = int((time.time() - start_time) * 1000)
                results[tool_id] = result.to_dict()
                previous_results[tool_id] = result.data or {}
            
            return {
                'workflow_success': all(r.get('success', False) for r in results.values()),
                'steps': results,
                'step_count': len(workflow_steps)
            }
        
        except Exception as e:
            self.logger.error(f"Workflow execution error: {str(e)}", exc_info=True)
            return {
                'workflow_success': False,
                'error': str(e),
                'steps': results,
                'step_count': len(workflow_steps)
            }
    
    def get_execution_telemetry(self) -> Dict[str, Any]:
        """Return execution telemetry."""
        return {
            'registered_tools': len(self.registry.list_tools()),
            'tools': [
                {'id': t['tool_id'], 'name': t['display_name']}
                for t in self.registry.list_tools()
            ]
        }


# Global engine instance
_global_engine: Optional[ToolExecutionEngine] = None


def get_execution_engine(registry: Optional[ToolRegistry] = None) -> ToolExecutionEngine:
    """Get or create global execution engine."""
    global _global_engine
    if _global_engine is None:
        _global_engine = ToolExecutionEngine(registry)
    return _global_engine


def reset_execution_engine() -> None:
    """Reset engine (for testing)."""
    global _global_engine
    _global_engine = None
