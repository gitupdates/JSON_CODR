from web_app.core.adapters import AdapterEvent, CapabilityAdapter, CapabilityCall, CapabilityExecutionError, ExecutionContext
from web_app.core.agent_runtime import AgentRuntime
from web_app.core.analysis_adapter import AnalysisAdapter
from web_app.core.api import create_core_router
from web_app.core.component_manager import ComponentManager
from web_app.core.component_registry import ComponentPlan, ComponentRegistry, ComponentRequest, ComponentScope, ComponentSource
from web_app.core.assimilation import (
    AssimilationService,
    ComponentManifest,
    FunctionalProbeResult,
    ProvenanceRecord,
    QuarantineRecord,
)
from web_app.core.browser_adapter import BrowserAdapter
from web_app.core.capabilities import CapabilityRegistry
from web_app.core.component_registry import (
    ComponentActivation,
    ComponentGeneration,
    ComponentLease,
    ComponentPlan,
    ComponentRegistry,
    ComponentRequest,
    ComponentScope,
    ComponentSource,
)
from web_app.core.contracts import (
    CapabilityManifest,
    CapabilityResult,
    CapabilityStatus,
    ExecutionMode,
    ManifestAuthority,
    ModelScope,
    ProbeObservation,
    ProjectId,
    RuntimeIdentity,
    TaskCommand,
    TaskEvent,
    TaskEventDraft,
    TaskId,
    TaskRecord,
    TaskStatus,
    ThreadId,
)
from web_app.core.context_service import CompactionRecord, ContextBundle, ContextService, ContextSource
from web_app.core.credentials import CredentialBroker
from web_app.core.delegation import DelegationService
from web_app.core.hooks import HookRegistry
from web_app.core.inference_adapter import InferenceAdapter
from web_app.core.language_adapter import LanguageAdapter
from web_app.core.memory import MemoryRecord, MemoryStore
from web_app.core.migration import MigrationInspection, MigrationReport, MigrationService
from web_app.core.mcp_adapter import McpAdapter
from web_app.core.provider_manager import ProviderManager
from web_app.core.provider_protocol import ProviderEvent, ProviderLock, ProviderManifest, ProviderProcess, ProviderRequest
from web_app.core.resources import ResourceBudget, ResourceDecision, ResourceSample
from web_app.core.scheduler import ApschedulerTriggerBackend, ScheduleService
from web_app.core.policy import PolicyDecision, PolicyEffect, PolicyService
from web_app.core.project_adapter import CheckpointRecord, ProjectAdapter, ProjectSnapshot
from web_app.core.project_watch import ExternalChangeEvent, ProjectWatcher
from web_app.core.service import CoreService
from web_app.core.router import ExecutionCandidate, ExecutionRoute, ExecutionRouter, RouteConsentRequired
from web_app.core.terminal_adapter import TerminalAdapter, TerminalSessionRecord

__all__ = [
    "AdapterEvent",
    "CapabilityAdapter",
    "CapabilityCall",
    "CapabilityExecutionError",
    "CapabilityManifest",
    "CapabilityRegistry",
    "CapabilityResult",
    "CapabilityStatus",
    "CheckpointRecord",
    "CompactionRecord",
    "ContextBundle",
    "ContextService",
    "ContextSource",
    "CoreService",
    "CredentialBroker",
    "DelegationService",
    "AgentRuntime",
    "AnalysisAdapter",
    "create_core_router",
    "ComponentManager",
    "ComponentPlan",
    "ComponentRegistry",
    "ComponentRequest",
    "ComponentScope",
    "ComponentSource",
    "ApschedulerTriggerBackend",
    "AssimilationService",
    "BrowserAdapter",
    "ComponentManifest",
    "ComponentActivation",
    "ComponentGeneration",
    "ComponentLease",
    "ComponentPlan",
    "ComponentRegistry",
    "ComponentRequest",
    "ComponentScope",
    "ComponentSource",
    "ExecutionCandidate",
    "ExecutionMode",
    "ExecutionContext",
    "ExecutionRoute",
    "ExecutionRouter",
    "FunctionalProbeResult",
    "HookRegistry",
    "ExternalChangeEvent",
    "ManifestAuthority",
    "MemoryRecord",
    "MemoryStore",
    "MigrationInspection",
    "MigrationReport",
    "MigrationService",
    "McpAdapter",
    "ModelScope",
    "ProbeObservation",
    "PolicyDecision",
    "PolicyEffect",
    "PolicyService",
    "ProviderEvent",
    "ProviderLock",
    "ProviderManager",
    "ProviderManifest",
    "ProviderProcess",
    "ProviderRequest",
    "ProjectId",
    "ProjectAdapter",
    "ProjectSnapshot",
    "ProjectWatcher",
    "ProvenanceRecord",
    "QuarantineRecord",
    "RuntimeIdentity",
    "ResourceBudget",
    "ResourceDecision",
    "ResourceSample",
    "RouteConsentRequired",
    "ScheduleService",
    "TaskCommand",
    "TaskEvent",
    "TaskEventDraft",
    "TaskId",
    "TaskRecord",
    "TaskStatus",
    "TerminalAdapter",
    "TerminalSessionRecord",
    "ThreadId",
    "InferenceAdapter",
    "LanguageAdapter",
]
