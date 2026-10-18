"""RevelaAI Automation Fabric: deterministic, permission-gated tool execution."""

from .registry import tool_catalog
from .engine import create_plan, execute_plan, AutomationError

__all__ = ["tool_catalog", "create_plan", "execute_plan", "AutomationError"]
