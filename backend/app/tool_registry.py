"""
Tool Registry
=============

Defines the modular tool registration system for the Tool Execution Layer.

Each tool implements:
- tool_id: unique identifier
- display_name: user-facing tool name
- supported_intents: list of intent patterns
- execute(): main execution method
- safe_fallback(): graceful failure response

Registry pattern ensures clean, extensible tool loading without giant if/else chains.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolExecutionResult:
    """Structured result from tool execution."""
    tool_id: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    fallback_used: bool = False
    execution_ms: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'tool_id': self.tool_id,
            'success': self.success,
            'data': self.data,
            'error': self.error,
            'fallback_used': self.fallback_used,
            'execution_ms': self.execution_ms
        }


class BaseTool(ABC):
    """
    Base class for all executable tools.
    
    Subclasses must implement:
    - execute(): main tool logic
    - safe_fallback(): graceful failure response
    """
    
    def __init__(self, tool_id: str, display_name: str, supported_intents: List[str]):
        self.tool_id = tool_id
        self.display_name = display_name
        self.supported_intents = supported_intents
        self.logger = logging.getLogger(f"tool.{tool_id}")
    
    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        """
        Execute the tool with given context.
        
        Args:
            context: Dict containing:
                - message: original user prompt
                - user_id: user identifier
                - memory_context: available memory (if any)
                - memory_preferences: user preferences (if any)
                - tool_params: tool-specific parameters
        
        Returns:
            ToolExecutionResult with structured output
        """
        pass
    
    @abstractmethod
    def safe_fallback(self, error_reason: str) -> Dict[str, Any]:
        """
        Return graceful fallback response if execution fails.
        
        Args:
            error_reason: why execution failed
        
        Returns:
            Dict with fallback content
        """
        pass
    
    def matches_intent(self, intent: str) -> bool:
        """Check if this tool handles the given intent."""
        intent_lower = intent.lower()
        return any(
            pattern.lower() in intent_lower 
            for pattern in self.supported_intents
        )


class ToolRegistry:
    """
    Central registry for all available tools.
    
    Supports:
    - registration
    - discovery by intent
    - execution orchestration
    """
    
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self.logger = logging.getLogger("tool_registry")
    
    def register(self, tool: BaseTool) -> None:
        """Register a tool in the registry."""
        if tool.tool_id in self._tools:
            self.logger.warning(f"Overwriting existing tool: {tool.tool_id}")
        self._tools[tool.tool_id] = tool
        self.logger.info(f"Registered tool: {tool.tool_id} ({tool.display_name})")
    
    def get_tool(self, tool_id: str) -> Optional[BaseTool]:
        """Get a specific tool by ID."""
        return self._tools.get(tool_id)
    
    def find_matching_tools(self, intent: str) -> List[BaseTool]:
        """Find all tools that match the given intent."""
        matching = []
        for tool in self._tools.values():
            if tool.matches_intent(intent):
                matching.append(tool) # type: ignore
        return matching # type: ignore
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools with metadata."""
        return [
            {
                'tool_id': tool.tool_id,
                'display_name': tool.display_name,
                'supported_intents': tool.supported_intents
            }
            for tool in self._tools.values()
        ]
    
    def has_tool(self, tool_id: str) -> bool:
        """Check if tool is registered."""
        return tool_id in self._tools


# Global registry instance
_global_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Get or create the global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def reset_registry() -> None:
    """Reset registry (for testing)."""
    global _global_registry
    _global_registry = None
