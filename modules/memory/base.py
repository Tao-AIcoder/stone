"""
modules/memory/base.py - Backward-compatible alias for ShortTermMemoryInterface.

New code should import directly from modules.interfaces.memory.
"""

from modules.interfaces.memory import ShortTermMemoryInterface

# Alias kept for backward compatibility
ShortTermMemory = ShortTermMemoryInterface

__all__ = ["ShortTermMemory", "ShortTermMemoryInterface"]
