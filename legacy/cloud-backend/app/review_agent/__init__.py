"""Public Task C API for the local backend and offline acceptance."""
from .engine import ReviewAgent, edit_suggestion
from .gateway import MemoryGateway, TaskGateway
from .models import AgentConfig, Approval, Failure, ReviewError, ReviewResult, Selection, TaskInput, TextSlice
from .provider import DeepSeekProvider, MockProvider, SystemCredentialStore
from .scope import preview_scope

__all__ = ["AgentConfig", "Approval", "DeepSeekProvider", "Failure", "MemoryGateway", "MockProvider",
           "ReviewAgent", "ReviewError", "ReviewResult", "Selection", "SystemCredentialStore", "TaskGateway",
           "TaskInput", "TextSlice", "edit_suggestion", "preview_scope"]
