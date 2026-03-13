"""
modules/interfaces/ - Contractual ABCs for every replaceable STONE component.

Swap any implementation by:
1. Writing a class that inherits the relevant interface here.
2. Registering it in modules/registry.py under the desired driver name.
3. Changing the "driver" field in stone.config.json.
Zero business-code changes required.
"""

from modules.interfaces.gateway import GatewayInterface
from modules.interfaces.memory import ShortTermMemoryInterface, LongTermMemoryInterface
from modules.interfaces.model_router import ModelRouterInterface
from modules.interfaces.auth import AuthInterface
from modules.interfaces.audit import AuditInterface
from modules.interfaces.sandbox import SandboxInterface, SandboxResult
from modules.interfaces.prompt_guard import PromptGuardInterface

__all__ = [
    "GatewayInterface",
    "ShortTermMemoryInterface",
    "LongTermMemoryInterface",
    "ModelRouterInterface",
    "AuthInterface",
    "AuditInterface",
    "SandboxInterface",
    "SandboxResult",
    "PromptGuardInterface",
]
