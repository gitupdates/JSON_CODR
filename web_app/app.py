from pathlib import Path

import asyncio
from dataclasses import asdict
import os
import re
import sys
from typing import Callable, Literal
from uuid import uuid7

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder

from web_app.attachments import AttachmentService, AttachmentTooLarge
from web_app.agui import build_prompt as build_agui_prompt, stream_events as stream_agui_events
from web_app.actions import ActionProposalService
from web_app.artifacts import ArtifactService
from web_app.context import ContextAssembler
from web_app.conversation import ConversationService
from web_app.hardware import HardwareBackendManager
from web_app.inference.catalog import OptimizedModelCatalog
from web_app.inference.contracts import ProviderKind
from web_app.inference.detection import AcceleratorDetector
from web_app.inference.environments import EnvironmentManager
from web_app.inference.providers.registry import ProviderRegistry
from web_app.inference.router import InferenceRouter
from web_app.inference.sidecar import SidecarClient
from web_app.inference.compatibility import attach_agent_compatibility, ollama_model_status, optimized_model_status
from web_app.inference.search import OptimizedModelSearch
from web_app.localperf.package import LocalPerfPackageError, LocalPerfPackageService
from web_app.localperf.storage import LocalPerfStorage
from web_app.integrations.discovery import build_discovery_document
from web_app.integrity_benchmark import IntegrityBenchmarkService
from web_app.benchmark_baseline import BenchmarkBaselineService
from web_app.coding_agents import CodingAgentService
from web_app.github_cli import GitHubCLI, GitHubCLIError
from web_app.github_auth import GitHubAuthSessionConflict, GitHubAuthSessionNotFound, GitHubAuthSessionService
from web_app.git_broker import GitBrokerService
from web_app.git_adapter import GitActionAdapter
from web_app.core.adapters import CapabilityCall
from web_app.core.approval import ApprovalStore
from web_app.core.agent_runtime import AgentRuntime
from web_app.core.agent_services import (
    EventEvidenceVerifier,
    InferencePlanner,
    ProjectContextResolver,
    planner_output_schema,
    select_agent_planner_model,
)
from web_app.core.api import create_core_router
from web_app.core.artifact_store import ArtifactStore
from web_app.core.assimilation import AssimilationService, FunctionalProbeResult, SkillInstallAdapter
from web_app.core.contracts import CompletionCriterion, CriterionKind, GoalSpec, TaskCommand, TaskStatus
from web_app.core.git_adapter import GitExecutionAdapter
from web_app.core.inference_adapter import InferenceAdapter
from web_app.core.context_service import ContextService
from web_app.core.memory import MemoryStore
from web_app.core.model_conformance import ModelConformanceStore
from web_app.core.mcp_stdio_backend import build_mcp_adapters
from web_app.core.policy import PolicyService
from web_app.core.project_adapter import ProjectAdapter
from web_app.core.project_intelligence import ProjectReader
from web_app.core.project_registry import ProjectRegistry
from web_app.core.service import CoreService
from web_app.core.store import TaskStore
from web_app.core.component_manager import ComponentManager
from web_app.core.component_catalog import active_component_command
from web_app.core.component_adapter import LazyComponentExecutionAdapter
from web_app.core.capability_catalog import CapabilityCatalog, CapabilityDefinition, lifecycle_definitions
from web_app.core.capability_discovery import discover_project_profile
from web_app.core.canonical import canonical_digest
from web_app.core.terminal_adapter import TerminalAdapter
from web_app.dependencies import DependencyService
from web_app.models import ActionApprovalRequest, ActionSuggestion, AttachmentUpdate, BrokerAdapterRunRequest, BrokerGrantRequest, BrokerTaskRequest, ChatMessage, ChatRequest, ChatResult, ClipboardTextRequest, CodingAgentGrantRequest, CodingAgentLaunchRequest, DestructiveConfirmationRequest, DiscoveryInstallRequest, GitHubAuthCancelRequest, GitHubAuthLoginRequest, GitHubBuildCheckRequest, GitHubBuildUpdateRequest, GitHubConfirmedWrite, GitHubIssueCommentRequest, GitHubIssueCreateRequest, GitHubIssueUpdateRequest, GitHubLocalBranchRequest, GitHubLocalCloneRequest, GitHubLocalCommitRequest, GitHubLocalPushRequest, GitHubLocalStageRequest, GitHubLocalSyncRequest, GitHubPullRequestCreateRequest, GitHubPullRequestMergeRequest, GitHubPullRequestUpdateRequest, GitHubReleaseCreateRequest, GitHubReleaseUpdateRequest, GitHubRemoteBranchCreateRequest, GitHubRepositoryCreateRequest, GitHubRepositoryDeleteRequest, GitHubRepositoryUpdateRequest, GithubSkillInstallRequest, GithubSkillPreviewRequest, GpuProfileSettings, HardwareBenchmarkRequest, HardwareProbeRequest, IntegrityBenchmarkRequest, KnownSkillScanRequest, ModelRunCreateRequest, OptimizedModelInstallRequest, ProjectWorkspaceRunRequest, SessionSkillRoutingUpdate, SettingsUpdate, SkillPack, SkillPackRenameRequest, SkillRecommendationRequest, SkillScanRequest, SkillSelectionRequest, SkillUpdateRequest, TerminalCreateRequest, WorkspaceTaskRequest, WorkspaceTaskResponse
from web_app.model_run_store import ModelRunStore, RequestKeyConflict
from web_app.model_runs import ModelRunService, canonical_model_prompt
from web_app.ollama_service import (
    ModelOutputError,
    ModelTimeoutError,
    OllamaService,
    OllamaUnavailableError,
)
from web_app.workspace import InvalidSessionId, WorkspaceService, default_data_root
from web_app.terminal import TerminalService
from web_app.skills import DuplicateSkillPack, GithubSkillService, SkillConverterService, SkillDiscoveryService, SkillLibraryService
from web_app.settings import SettingsService
from web_app.skillsets import SkillsetService
from web_app.recommendations import SkillRecommendationService
from web_app.version import APP_VERSION


def configure_local_analysis_tools(data_root: Path) -> None:
    if not os.environ.get("GHIDRA_INSTALL_DIR"):
        candidates = sorted((Path(data_root) / "tools").glob("ghidra_*_PUBLIC"), reverse=True)
        if candidates:
            os.environ["GHIDRA_INSTALL_DIR"] = str(candidates[0].resolve())
    if not os.environ.get("JAVA_HOME") and os.name == "nt":
        candidates = sorted(Path("C:/Program Files/Microsoft").glob("jdk-*-hotspot"), reverse=True)
        if candidates:
            java_home = str(candidates[0].resolve())
            os.environ["JAVA_HOME"] = java_home
            java_bin = str(Path(java_home) / "bin")
            if java_bin.casefold() not in os.environ.get("PATH", "").casefold().split(os.pathsep):
                os.environ["PATH"] = f"{java_bin}{os.pathsep}{os.environ.get('PATH', '')}"


def create_app(
    service: OllamaService,
    workspace: WorkspaceService | None = None,
    attachments: AttachmentService | None = None,
    terminals: TerminalService | None = None,
    hardware: HardwareBackendManager | None = None,
    optimized: bool = False,
    integrity: IntegrityBenchmarkService | None = None,
    coding_agents: CodingAgentService | None = None,
    git_broker: GitBrokerService | None = None,
    github_skills: GithubSkillService | None = None,
    github_cli: GitHubCLI | None = None,
    github_auth: GitHubAuthSessionService | None = None,
) -> FastAPI:
    application = FastAPI(title="JSON_CODR", version=APP_VERSION)
    workspace = workspace or WorkspaceService(default_data_root())
    component_manager = None
    component_root = workspace.data_root / "core" / "component-registry"

    def get_component_manager() -> ComponentManager:
        nonlocal component_manager
        if component_manager is None:
            component_manager = ComponentManager(component_root)
            application.state.component_manager = component_manager
        return component_manager
    configure_local_analysis_tools(workspace.data_root)
    attachments = attachments or AttachmentService(workspace)
    skill_library = SkillLibraryService(workspace.data_root)
    skill_library.ensure_builtin_rea()
    skill_library.ensure_builtin_multi_model_jury()
    skill_library.ensure_builtin_readteam()
    skill_library.ensure_envelopes()
    skill_converter = SkillConverterService()
    settings = SettingsService(workspace.data_root)
    if hasattr(service, "set_optimization_provider"):
        service.set_optimization_provider(settings.optimization_for)
    catalog = OptimizedModelCatalog()
    environment_manager = EnvironmentManager(workspace.data_root)
    clients = {
        provider: SidecarClient(environment_manager.plan(provider).python)
        for provider in (ProviderKind.openvino, ProviderKind.ryzen_ai, ProviderKind.winml, ProviderKind.directml)
        if environment_manager.plan(provider).python.is_file()
    }
    inference_router = InferenceRouter(
        service, catalog, ProviderRegistry(clients, workspace.data_root / "optimized-models"), set()
    ) if optimized else None
    hardware = hardware or HardwareBackendManager(
        workspace.data_root,
        accelerator_detector=AcceleratorDetector(
            runtime_available=lambda provider: environment_manager.status(ProviderKind(provider))["status"] == "ready",
            provider_devices=lambda provider: environment_manager.provider_devices(ProviderKind(provider)),
            model_ready=lambda provider: environment_manager.model_ready(ProviderKind(provider)),
        ) if optimized else None,
    )
    localperf_packages = LocalPerfPackageService(LocalPerfStorage(workspace.data_root))
    benchmark_baselines = BenchmarkBaselineService(workspace.data_root)
    integrity_generation_available = integrity is not None or callable(getattr(service, "generate_deterministic", None))
    async def generate_integrity(model: str, messages: list[dict], temperature: float) -> str:
        generator = getattr(service, "generate_deterministic", None)
        if generator is None:
            raise RuntimeError("Integrity benchmarks are unavailable for this model service")
        return await generator(model, messages, temperature)
    integrity = integrity or IntegrityBenchmarkService(
        workspace.data_root,
        generate_integrity,
        response_timeout_seconds=int(getattr(service, "timeout_seconds", 180)),
    )
    optimized_search = OptimizedModelSearch(catalog=catalog)
    skillsets = SkillsetService(workspace.data_root, skill_library)
    recommendations = SkillRecommendationService(skill_library, skillsets, settings)
    skill_discovery = SkillDiscoveryService(skill_library, skill_converter, workspace.data_root)
    github_skills = github_skills or GithubSkillService(skill_library, skill_converter, workspace.data_root)
    github_cli = github_cli or GitHubCLI()
    github_auth = github_auth or GitHubAuthSessionService(status_probe=lambda: github_cli.status())
    application.router.add_event_handler("shutdown", github_auth.close)
    context_assembler = ContextAssembler(attachments, skills=skill_library)
    model_run_store = ModelRunStore(workspace.data_root)
    model_runs = ModelRunService(
        model_run_store,
        inference_router or service,
        workspace,
        context_assembler,
        concurrency=4,
    )
    application.state.model_runs = model_runs
    model_run_tasks: set[asyncio.Task] = set()
    application.state.model_run_tasks = model_run_tasks

    def finish_model_run(task: asyncio.Task) -> None:
        model_run_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def close_model_runs() -> None:
        for task in model_run_tasks:
            task.cancel()
        if model_run_tasks:
            await asyncio.gather(*model_run_tasks, return_exceptions=True)

    application.router.add_event_handler("startup", model_runs.recover_incomplete_runs)
    application.router.add_event_handler("shutdown", close_model_runs)
    dependency_service = DependencyService(attachments)
    artifact_service = ArtifactService(workspace)
    conversation_service = ConversationService(
        workspace,
        attachments,
        Path(__file__).resolve().parent.parent,
        artifact_service,
    )
    terminals = terminals or TerminalService(shim_root=component_root / "shims")
    close_terminals = getattr(terminals, "close_all", None)
    if close_terminals is not None:
        application.router.add_event_handler("shutdown", close_terminals)
    def close_component_manager() -> None:
        if component_manager is not None:
            component_manager.close()

    application.router.add_event_handler("shutdown", close_component_manager)
    coding_agents = coding_agents or CodingAgentService(workspace.data_root)
    git_broker = git_broker or GitBrokerService(workspace.data_root, verification_checks={
        "python-compile": [sys.executable, "-m", "compileall", "-q", "."],
        "python-tests": [sys.executable, "-m", "pytest", "-q"],
        "node-tests": ["npm", "test"],
        "node-lint": ["npm", "run", "lint"],
        "node-build": ["npm", "run", "build"],
        "git-diff-check": ["git", "diff", "--check"],
    })
    git_adapter = GitActionAdapter(verification_checks=git_broker.verification_checks)
    git_broker.recover_interrupted_tasks()
    core_runtime = None
    core_memory = None
    core_approvals = None
    core_projects = None
    core_conformance = None
    core_artifacts = None
    core_capabilities = ()
    core_mcp_backends = []

    async def probe_component(manifest, staged):
        if manifest.kind != "skill-pack":
            return FunctionalProbeResult(success=False, reason="Unsupported component kind")
        try:
            payload_path = next(staged.iterdir())
            pack = SkillPack.model_validate_json(payload_path.read_text(encoding="utf-8"))
        except (OSError, StopIteration, ValueError) as error:
            return FunctionalProbeResult(success=False, reason=f"Invalid skill pack: {error}")
        if not pack.skills or any("JSON_CODR_SKILL_SCHEMA: 1" not in skill.content for skill in pack.skills):
            return FunctionalProbeResult(success=False, reason="Skill pack is missing the JSON_CODR envelope")
        return FunctionalProbeResult(success=True, evidence=f"verified:{manifest.content_digest}")

    def resolve_skill_install(source_kind: str, reference: dict):
        if source_kind == "discovery":
            return skill_discovery.prepare_install(str(reference["discovery_id"]))
        if source_kind == "github":
            return github_skills.prepare_install(str(reference["preview_id"]))
        if source_kind == "attachment":
            return convert_attachment(str(reference["session_id"]), str(reference["attachment_id"])), lambda: None
        raise ValueError("Unsupported skill source")

    def get_core_runtime():
        nonlocal core_runtime, core_capabilities, core_memory, core_approvals, core_projects, core_conformance
        if core_runtime is None:
            core_root = workspace.data_root / "core"
            core_conformance = ModelConformanceStore(core_root / "model-conformance.sqlite")
            application.state.core_model_conformance = core_conformance
            core_tasks = TaskStore(core_root / "tasks.sqlite")
            core_policy = PolicyService(core_root / "policy.sqlite")
            core_terminal_adapter = TerminalAdapter(terminals)
            core_project_adapter = ProjectAdapter(core_root / "project-state")
            def prepare_inference_prompt(call, prompt):
                model = call.arguments.get("model")
                if not isinstance(model, str):
                    raise ValueError("inference generation requires model")
                session_id = call.arguments.get("session_id")
                if not isinstance(session_id, str):
                    return canonical_model_prompt(model=model, task=prompt, assembled_prompt=prompt), {}
                session = workspace.get_session(session_id)
                recommendation_result = recommendations.recommend(session, prompt)
                context_result = context_assembler.build(session, prompt, recommendation_result)
                return canonical_model_prompt(
                    model=model,
                    task=prompt,
                    assembled_prompt=context_result.prompt,
                ), {
                    "attached_skills": [item.model_dump(mode="json") for item in context_result.attached_skills],
                    "attached_skillsets": context_result.skillsets,
                    "skill_recommendations": [
                        item.model_dump(mode="json") for item in recommendation_result.recommendations
                    ],
                }

            from cli import load_config
            from web_app.core.model_tags import ModelTagRegistry
            from web_app.core.native_primitives import NativePrimitiveAdapter
            from web_app.core.native_ollama import NativeOllamaTransport

            model_registry = ModelTagRegistry.load(Path(__file__).resolve().parent.parent / "zero_layer_models.json")
            native_config = load_config()
            inference_backend = (
                NativeOllamaTransport(str(native_config["host"]))
                if isinstance(service, OllamaService)
                else (inference_router or service)
            )
            core_inference_adapter = InferenceAdapter(
                inference_backend,
                prepare_prompt=prepare_inference_prompt,
                model_registry=model_registry if isinstance(service, OllamaService) else None,
            )
            core_git_adapter = GitExecutionAdapter(
                git_broker,
                lambda grant_id, project_root: coding_agents.authorized_grant(grant_id, project_root, "broker"),
            )
            component_adapter = SkillInstallAdapter(
                AssimilationService(core_root / "components", probe_component),
                resolve_skill_install,
                skill_library.install,
                DuplicateSkillPack,
            )
            native_primitives = NativePrimitiveAdapter(core_project_adapter, core_terminal_adapter)
            adapters = {
                "git.execute": core_git_adapter,
                "inference.generate": core_inference_adapter,
                "project.read": core_project_adapter,
                "project.search": core_project_adapter,
                "project.patch": core_project_adapter,
                "checkpoint.create": core_project_adapter,
                "checkpoint.restore": core_project_adapter,
                "terminal.session": core_terminal_adapter,
                "terminal.execute": core_terminal_adapter,
                "terminal.interrupt": core_terminal_adapter,
                "terminal.close": core_terminal_adapter,
                "native.read": native_primitives,
                "native.write": native_primitives,
                "native.edit": native_primitives,
                "native.shell": native_primitives,
                "component.install": component_adapter,
                "component.execute": LazyComponentExecutionAdapter(get_component_manager),
            }
            craft_command = active_component_command(component_root, "craft-anything-cli")
            mcp_adapters, mcp_backends = build_mcp_adapters(
                workspace.data_root / "mcp_servers.json",
                rea_provider_root=workspace.data_root / "providers" / "rea",
                craft_command=craft_command,
            )
            adapters.update(mcp_adapters)
            core_mcp_backends.extend(mcp_backends)
            project_root = Path(__file__).resolve().parent.parent
            definitions = list(lifecycle_definitions())
            defined_ids = {item.capability_id for item in definitions}
            for capability_id in sorted(set(adapters) - defined_ids):
                definitions.append(CapabilityDefinition(
                    capability_id=capability_id, version="1",
                    description=f"Extension capability {capability_id}",
                    input_schema={"type": "object"}, effect_class="extension",
                    approval_class="exact", rollback_class="adapter",
                    adapter_id=capability_id,
                    adapter_digest=canonical_digest({"adapter": capability_id, "version": "1"}),
                ))
            capability_catalog = CapabilityCatalog(definitions, probed_adapters=set(adapters))
            project_profile = discover_project_profile(project_root)
            application.state.core_capability_catalog = capability_catalog
            application.state.core_project_profile = project_profile
            agent_runtime = None

            async def run_agent(task_id: str):
                if agent_runtime is None:
                    raise RuntimeError("agent runtime is not initialized")
                return await agent_runtime.run(task_id)

            core_projects = ProjectRegistry(core_root / "projects.sqlite")
            registered_project = core_projects.register(project_root, project_id="legacy")
            application.state.core_project_registry = core_projects
            application.state.core_default_project_id = registered_project.project_id

            def agent_project_fingerprint(root: str | None) -> str:
                reader = ProjectReader(root or project_root)
                instruction_paths = {
                    instruction.relative_path for instruction in reader.instructions_for(".")
                }
                files = tuple(
                    project_file for project_file in reader.files()
                    if project_file.relative_path not in instruction_paths
                )
                return reader.fingerprint(files)

            core_approvals = ApprovalStore(core_root / "approvals.sqlite")
            application.state.core_approval_store = core_approvals
            core_service = CoreService(
                core_tasks,
                core_policy,
                adapters,
                restore_checkpoint=core_project_adapter.restore,
                agent_runner=run_agent,
                approval_store=core_approvals,
                project_fingerprint=agent_project_fingerprint,
            )
            resolver = ProjectContextResolver(core_projects)
            core_memory = MemoryStore(core_root / "memory.sqlite")
            application.state.core_memory = core_memory

            async def generate_agent_plan(model: str, prompt: str) -> str:
                json_chat = getattr(inference_backend, "json_chat", None)
                if callable(json_chat):
                    return await json_chat(
                        model,
                        prompt,
                        capability_catalog.planner_schema(set(project_profile.kinds)),
                    )
                stream_chat = getattr(inference_backend, "stream_chat", None)
                if callable(stream_chat):
                    async for event in stream_chat(model, prompt):
                        if event.get("type") == "completed":
                            return event["result"].content
                    raise ValueError("planner model returned no completed result")
                return (await service.chat(model, prompt)).content

            planner = InferencePlanner(
                generate_agent_plan,
                model=select_agent_planner_model(native_config),
            )
            agent_runtime = AgentRuntime(
                core_tasks,
                core_service,
                ContextService(core_tasks, core_memory),
                planner,
                EventEvidenceVerifier(),
                agent_project_fingerprint,
                project_reader_resolver=resolver.resolve,
            )
            application.state.agent_runtime = agent_runtime
            core_capabilities = tuple({
                **item.definition.model_dump(mode="json"),
                "available": item.available,
                "reasons": item.reasons,
            } for item in capability_catalog.list_for_project(set(project_profile.kinds)))
            core_runtime = (core_service, core_tasks, core_policy)
            application.state.core_service = core_service
            application.state.core_task_store = core_tasks
            application.state.core_policy = core_policy
        return core_runtime

    def get_core_artifacts() -> ArtifactStore:
        nonlocal core_artifacts
        if core_artifacts is None:
            core_root = workspace.data_root / "core"
            core_artifacts = ArtifactStore(core_root / "artifacts", core_root / "artifacts.sqlite")
            application.state.core_artifact_store = core_artifacts
        return core_artifacts

    async def close_core_runtime() -> None:
        await asyncio.gather(*(backend.close() for backend in core_mcp_backends), return_exceptions=True)
        if core_runtime is not None:
            core_service, core_tasks, core_policy = core_runtime
            await core_service.shutdown()
            if core_artifacts is not None:
                core_artifacts.close()
            core_policy.close()
            core_tasks.close()
            if core_approvals is not None:
                core_approvals.close()
            if core_projects is not None:
                core_projects.close()
            if core_conformance is not None:
                core_conformance.close()
            if core_memory is not None:
                core_memory.close()

    application.router.add_event_handler("shutdown", close_core_runtime)
    application.include_router(
        create_core_router(
            get_core_runtime,
            artifact_store=get_core_artifacts,
            capabilities=lambda: core_capabilities if get_core_runtime() else (),
            components=get_component_manager,
        )
    )
    action_proposals = ActionProposalService()
    web_root = Path(__file__).resolve().parent.parent / "web"
    application.mount("/static", StaticFiles(directory=web_root), name="static")

    @application.get("/", include_in_schema=False)
    async def index():
        return FileResponse(web_root / "index.html")

    @application.get("/api/health")
    async def health():
        result = await service.health()
        return {"status": "ready" if result["ollama"] else "degraded", "app_version": APP_VERSION, **result}

    @application.get("/.well-known/json-codr")
    async def json_codr_discovery(request: Request):
        requested_origin = str(request.base_url).rstrip("/")
        requested_host = request.url.hostname
        configured_origin = os.environ.get("JSON_CODR_PUBLIC_URL")
        service_origin = configured_origin or (
            requested_origin
            if requested_host in {"127.0.0.1", "localhost", "::1"}
            else "http://127.0.0.1:8874"
        )
        return build_discovery_document(
            service_origin,
            os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        )

    @application.post("/api/benchmarks/baseline")
    async def export_benchmark_baseline():
        artifact = benchmark_baselines.export(integrity.history(), hardware.benchmark_history())
        return {
            "filename": artifact.path.name,
            "path": str(artifact.path),
            "download_url": f"/api/benchmarks/baselines/{artifact.path.name}",
            "model_count": artifact.model_count,
            "integrity_count": artifact.integrity_count,
            "performance_session_count": artifact.performance_session_count,
        }

    @application.get("/api/benchmarks/baselines/{filename}")
    async def download_benchmark_baseline(filename: str):
        if Path(filename).name != filename or not re.fullmatch(r"JSON_CODR-benchmark-baseline-\d{8}T\d{6}Z\.json", filename):
            raise HTTPException(status_code=400, detail="Invalid baseline filename")
        path = benchmark_baselines.root / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Benchmark baseline not found")
        return FileResponse(path, media_type="application/json", filename=filename)

    @application.get("/api/models")
    async def models():
        try:
            return {"models": await (inference_router.list_models() if inference_router else service.list_models())}
        except OllamaUnavailableError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @application.post("/api/model-runs", status_code=201)
    async def create_model_run(request: ModelRunCreateRequest):
        try:
            workspace.get_session(request.session_id)
            run = await model_runs.create(request)
            task = asyncio.create_task(model_runs.run(run.run_id))
            model_run_tasks.add(task)
            task.add_done_callback(finish_model_run)
            return run
        except RequestKeyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.get("/api/model-runs/{run_id}")
    async def get_model_run(run_id: str):
        try:
            return model_runs.get(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error

    @application.get("/api/model-runs/{run_id}/results/{result_id}/original")
    async def get_model_run_original(run_id: str, result_id: str, x_json_codr: str | None = Header(None)):
        if x_json_codr != "1":
            raise HTTPException(status_code=403, detail="Local authorization required")
        try:
            return model_run_store.get_original(run_id, result_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Original output not found") from error

    @application.post("/api/model-runs/{run_id}/cancel")
    async def cancel_model_run(run_id: str):
        try:
            return model_runs.cancel(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error

    @application.get("/api/model-runs/{run_id}/export")
    async def export_model_run(run_id: str, format: str = "json"):
        try:
            media_type, content = model_runs.export(run_id, format)
            return Response(content=content, media_type=media_type)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/model-runs/{run_id}/search")
    async def search_model_run(run_id: str, q: str):
        try:
            return model_runs.search(run_id, q)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error

    @application.get("/api/models/{model:path}/tool-compatibility")
    async def model_tool_compatibility(model: str):
        try:
            return await service.tool_compatibility(model)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @application.get("/api/settings")
    async def get_settings():
        return settings.get()

    @application.get("/api/inference/catalog")
    async def inference_catalog():
        return [model.model_dump(mode="json") for model in catalog.list()]

    @application.get("/api/inference/models/search")
    async def search_inference_models(provider: ProviderKind, q: str = "coder", limit: int = 10):
        if provider is ProviderKind.ollama:
            raise HTTPException(status_code=400, detail="Search targets optional optimized providers")
        try:
            return await asyncio.to_thread(optimized_search.search, provider.value, q, limit)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/inference/models/install")
    async def install_optimized_model(request: OptimizedModelInstallRequest):
        if not request.confirmed:
            raise HTTPException(status_code=409, detail="Model download requires confirmation")
        try:
            model = catalog.get(request.model_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Only approved catalog models can be installed") from error
        try:
            path = await asyncio.to_thread(environment_manager.install_model, model)
            probe = await inference_router.probe(model.id) if inference_router else None
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return {
            "model_id": model.id,
            "provider": model.provider.value,
            "path": str(path),
            "installed": path.is_dir(),
            "verified": bool(probe and probe.success),
            "probe_error": probe.error if probe and not probe.success else None,
        }

    @application.get("/api/inference/environments")
    async def inference_environments():
        return [
            environment_manager.status(provider)
            for provider in ProviderKind
            if provider is not ProviderKind.ollama
        ]

    @application.get("/api/inference/install-plan/{provider}")
    async def inference_install_plan(provider: ProviderKind):
        if provider is ProviderKind.ollama:
            raise HTTPException(status_code=400, detail="Ollama uses the base installation")
        plan = environment_manager.plan(provider)
        return {
            "provider": provider.value,
            "command": environment_manager.install_command(provider),
            "environment": str(plan.root),
            "packages": plan.packages,
            "includes_driver": False,
        }

    @application.post("/api/sessions/{session_id}/hardware/{provider}/install-proposal")
    async def hardware_install_proposal(session_id: str, provider: ProviderKind):
        try:
            workspace.get_session(session_id)
        except (InvalidSessionId, KeyError) as error:
            raise HTTPException(status_code=404, detail="Session not found") from error
        if provider is ProviderKind.ollama:
            raise HTTPException(status_code=400, detail="Ollama uses the base installation")
        command = environment_manager.install_command(provider)
        provider_name = {
            ProviderKind.openvino: "OpenVINO",
            ProviderKind.ryzen_ai: "Ryzen AI",
            ProviderKind.winml: "WinML",
            ProviderKind.directml: "DirectML",
        }[provider]
        suggestion = ActionSuggestion(
            command=command,
            cwd=str(Path(__file__).resolve().parent.parent),
            explanation=f"Install the isolated {provider_name} runtime without drivers.",
        )
        return action_proposals.propose(session_id, [suggestion], [], str(Path(__file__).resolve().parent.parent))

    @application.patch("/api/settings")
    async def update_settings(request: SettingsUpdate):
        try:
            return settings.update(request)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.get("/api/hardware")
    async def hardware_status():
        return hardware.status()

    async def model_compatibility(detected: list[dict]) -> list[dict]:
        installed, running = await asyncio.gather(service.list_models(), service.running_models())
        installed_names = [item["name"] for item in installed if item.get("installed")]
        tool_routes = {
            name: route
            for name, route in zip(
                installed_names,
                await asyncio.gather(*(service.tool_compatibility(name) for name in installed_names)),
            )
        }
        configured_fallback = str(service.config.get("tool_fallback_model", "")).strip()
        fallback_route = tool_routes.get(configured_fallback)
        matrix = []
        for candidate in detected:
            backend = candidate["id"]
            if backend in {"cpu", "ollama_gpu"} or backend.startswith(("cuda_", "rocm_", "vulkan")):
                models = [
                    attach_agent_compatibility(
                        ollama_model_status(name, backend, running, bool(candidate.get("compatible"))),
                        tool_routes[name],
                    )
                    for name in installed_names
                ]
            else:
                models = []
                for model in catalog.list():
                    if model.provider.value != backend:
                        continue
                    installed_model = environment_manager.model_path(model).is_dir()
                    verified = bool(inference_router and model.id in inference_router.verified_models)
                    status = optimized_model_status(model, installed_model, bool(candidate.get("runtime_ready")), verified)
                    delegated = {
                        "advertised_tools": False,
                        "native_tools_verified": False,
                        "route": "delegated_verified" if fallback_route and fallback_route["available"] else "unavailable",
                        "effective_tool_model": fallback_route["effective_tool_model"] if fallback_route else None,
                        "available": bool(fallback_route and fallback_route["available"]),
                    }
                    models.append(attach_agent_compatibility(status, delegated))
            matrix.append({"backend": backend, "name": candidate["name"], "models": models})
        return matrix

    @application.post("/api/hardware/detect")
    async def detect_hardware():
        detected = hardware.detect()
        try:
            compatibility = await model_compatibility(detected)
        except OllamaUnavailableError as error:
            return [
                {**candidate, "compatible_models": [], "model_compatibility_error": str(error)}
                for candidate in detected
            ]
        models_by_backend = {group["backend"]: group["models"] for group in compatibility}
        return [{**candidate, "compatible_models": models_by_backend.get(candidate["id"], [])} for candidate in detected]

    @application.get("/api/hardware/model-compatibility")
    async def hardware_model_compatibility():
        return await model_compatibility(hardware.detect())

    @application.get("/api/hardware/telemetry")
    async def hardware_telemetry():
        gpus, running_models = await asyncio.gather(
            asyncio.to_thread(hardware.gpu_telemetry),
            service.running_models(),
        )
        return {"gpus": gpus, "models": running_models}

    @application.post("/api/hardware/probe")
    async def probe_hardware(request: HardwareProbeRequest):
        try:
            result = await hardware.probe(request.backend, request.model)
            if request.backend == "ollama_gpu" and result.get("verified"):
                optimization = settings.get().gpu_optimization
                optimization.model_profiles[request.model] = GpuProfileSettings(mode="gpu_preferred")
                settings.update(SettingsUpdate(gpu_optimization=optimization))
            return result
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/hardware/restore-cpu")
    async def restore_cpu_backend():
        return hardware.restore_cpu()

    @application.get("/api/hardware/benchmarks")
    async def hardware_benchmark_history():
        return hardware.benchmark_history()

    @application.delete("/api/hardware/benchmarks")
    async def clear_hardware_benchmarks():
        cleared = hardware.clear_legacy_benchmarks() if hasattr(hardware, "clear_legacy_benchmarks") else False
        benchmark_path = getattr(hardware, "benchmark_path", None)
        if benchmark_path and Path(benchmark_path).is_file():
            Path(benchmark_path).unlink()
            cleared = True
        return {"cleared": cleared, "history": []}

    @application.post("/api/hardware/benchmarks")
    async def run_hardware_benchmark(request: HardwareBenchmarkRequest):
        try:
            benchmark = await hardware.benchmark(request.suite, request.model, request.backend)
            hardware.apply_benchmark_selection(benchmark)
            if benchmark.get("selected_backend") == "ollama_gpu":
                optimization = settings.get().gpu_optimization
                optimization.model_profiles[request.model] = GpuProfileSettings(mode="gpu_preferred")
                settings.update(SettingsUpdate(gpu_optimization=optimization))
            return benchmark
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/api/integrity-benchmarks")
    async def integrity_benchmark_history():
        return integrity.history()

    @application.post("/api/integrity-benchmarks")
    async def run_integrity_benchmark(request: IntegrityBenchmarkRequest):
        if not integrity_generation_available:
            raise HTTPException(status_code=409, detail="Integrity benchmarks are unavailable for this model service")
        try:
            installed = {item["name"] for item in await service.list_models() if item.get("installed")}
        except Exception as error:
            raise HTTPException(status_code=503, detail="Unable to query installed models") from error
        if request.model not in installed:
            raise HTTPException(status_code=409, detail="Model is not installed")
        try:
            return await integrity.run(request.suite, request.model)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/api/localperf/packages/{evaluation_id}")
    async def export_localperf_package(evaluation_id: str, include_system_details: bool = False):
        try:
            artifact = localperf_packages.export(evaluation_id, include_system_details)
        except LocalPerfPackageError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return Response(
            content=artifact.content, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
        )

    @application.post("/api/localperf/packages/preview")
    async def preview_localperf_package(request: Request):
        try:
            preview = localperf_packages.preview(await request.body())
            return {
                "valid": preview.valid, "package_id": preview.package_id,
                "evaluation_id": preview.evaluation_id,
                "contains_system_details": preview.contains_system_details,
                "members": preview.members,
            }
        except LocalPerfPackageError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/localperf/packages/import", status_code=201)
    async def import_localperf_package(request: Request, retain_system_details: bool = False):
        try:
            record = localperf_packages.import_package(await request.body(), retain_system_details)
            return {
                "package_id": record.package_id, "path": str(record.path),
                "retained_system_details": record.retained_system_details,
                "source": "imported", "eligible_as_local_baseline": False,
            }
        except LocalPerfPackageError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/skillsets")
    async def list_skillsets():
        return skillsets.reconcile()

    @application.post("/api/sessions", status_code=201)
    async def create_session():
        return workspace.create_session()

    @application.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        try:
            return workspace.get_session(session_id)
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.get("/api/sessions/{session_id}/conversation")
    async def get_conversation(session_id: str):
        try:
            return conversation_service.history(session_id)
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.post("/api/sessions/{session_id}/conversation", status_code=201)
    async def append_conversation_message(session_id: str, message: ChatMessage):
        try:
            return conversation_service.append(session_id, message)
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.get("/api/sessions/{session_id}/conversation/export")
    async def export_conversation(
        session_id: str,
        format: str = "markdown",
        include_binaries: bool = False,
    ):
        try:
            payload, media_type, filename = conversation_service.export_session(
                session_id,
                format,
                include_binaries=include_binaries,
            )
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return Response(
            content=payload,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @application.get("/api/sessions/{session_id}/messages/{message_id}/export")
    async def export_conversation_message(
        session_id: str,
        message_id: str,
        format: str = "markdown",
    ):
        try:
            payload, media_type, filename = conversation_service.export_message(
                session_id,
                message_id,
                format,
            )
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Message not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return Response(
            content=payload,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @application.get("/api/sessions/{session_id}/references/{reference_id}")
    async def download_conversation_reference(session_id: str, reference_id: str):
        try:
            reference = conversation_service.find_reference(session_id, reference_id)
            path, media_type = conversation_service.resolve_reference(session_id, reference)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="Reference is outside the active scope") from error
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=404, detail="Reference not found") from error
        return FileResponse(path, media_type=media_type, filename=reference.label)

    @application.post("/api/sessions/{session_id}/skill-recommendations")
    async def preview_skill_recommendations(session_id: str, request: SkillRecommendationRequest):
        try:
            return recommendations.recommend(workspace.get_session(session_id), request.prompt)
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.patch("/api/sessions/{session_id}/skill-routing")
    async def update_session_skill_routing(session_id: str, request: SessionSkillRoutingUpdate):
        try:
            session = workspace.get_session(session_id)
            if request.excluded_skill_ids is not None:
                exclusions = list(dict.fromkeys(request.excluded_skill_ids))
                for reference in exclusions:
                    if ":" not in reference:
                        raise ValueError("Invalid skill reference")
                    pack_id, skill_id = reference.split(":", 1)
                    if not skill_library.get_skill(pack_id, skill_id).enabled:
                        raise ValueError("Disabled skills cannot be excluded")
                session.excluded_skill_ids = exclusions
            if request.auto_attach_skills is not None:
                session.auto_attach_skills = request.auto_attach_skills
            workspace.save_manifest(session)
            return session
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=422, detail="Unknown skill reference") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        try:
            workspace.delete_session(session_id)
            model_run_store.delete_session(session_id)
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error
        return Response(status_code=204)

    @application.get("/api/sessions/{session_id}/attachments")
    async def list_attachments(session_id: str):
        try:
            return workspace.get_session(session_id).attachments
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.post("/api/sessions/{session_id}/attachments", status_code=201)
    async def upload_attachment(
        session_id: str,
        file: UploadFile = File(...),
        relative_path: str | None = Form(None),
    ):
        try:
            return attachments.import_stream(
                session_id,
                file.filename or "attachment",
                file.file,
                relative_path=relative_path,
            )
        except AttachmentTooLarge as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        except (InvalidSessionId, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.post("/api/sessions/{session_id}/clipboard-text", status_code=201)
    async def paste_text(session_id: str, request: ClipboardTextRequest):
        try:
            return attachments.import_text(session_id, request.text)
        except (InvalidSessionId, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.get("/api/sessions/{session_id}/attachments/{attachment_id}/preview")
    async def preview_attachment(session_id: str, attachment_id: str):
        try:
            return attachments.preview(session_id, attachment_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error

    @application.get("/api/sessions/{session_id}/attachments/{attachment_id}/original")
    async def download_original(session_id: str, attachment_id: str):
        try:
            path, record = attachments.original_path(session_id, attachment_id)
            return FileResponse(
                path,
                media_type="application/octet-stream",
                filename=record.display_name,
                headers={"X-Content-Type-Options": "nosniff"},
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error

    @application.post("/api/sessions/{session_id}/attachments/{attachment_id}/retry")
    async def retry_attachment(session_id: str, attachment_id: str):
        try:
            return attachments.retry(session_id, attachment_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error

    @application.get("/api/sessions/{session_id}/archive.zip")
    async def export_session_archive(session_id: str):
        try:
            payload = attachments.export_zip(session_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error
        return Response(
            content=payload,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="json-codr-{session_id}.zip"'},
        )

    @application.get("/api/skills")
    async def list_skills():
        return skill_library.list()

    @application.get("/api/skills/standard/envelope.md")
    async def download_skill_envelope_standard():
        path = Path(__file__).resolve().parent.parent / "docs" / "user" / "json-codr-skill-envelope.md"
        return FileResponse(path, media_type="text/markdown", filename="json-codr-skill-envelope.md")

    @application.get("/api/skills/standard/envelope.schema.json")
    async def download_skill_envelope_schema():
        path = Path(__file__).resolve().parent.parent / "docs" / "user" / "json-codr-skill-envelope.schema.json"
        return FileResponse(path, media_type="application/schema+json", filename="json-codr-skill-envelope.schema.json")

    @application.post("/api/skills/scan")
    async def scan_skills(request: SkillScanRequest):
        try:
            result = skill_discovery.scan(request.directory)
            current = settings.get()
            if str(Path(request.directory).resolve()) not in current.skill_scan.approved_directories:
                current.skill_scan.approved_directories.append(str(Path(request.directory).resolve()))
                settings.update(SettingsUpdate(skill_scan=current.skill_scan))
            return result
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/skills/scan-upload")
    async def scan_uploaded_skills(
        files: list[UploadFile] = File(...),
        relative_paths: list[str] = Form(...),
    ):
        if len(files) != len(relative_paths):
            raise HTTPException(status_code=422, detail="Each uploaded file requires one relative path")
        try:
            entries: list[tuple[str, bytes]] = []
            total_bytes = 0
            for relative_path, file in zip(relative_paths, files, strict=True):
                data = await file.read(10 * 1024 * 1024 + 1)
                total_bytes += len(data)
                if total_bytes > 10 * 1024 * 1024:
                    raise ValueError("Folder upload is limited to 10 MB")
                entries.append((relative_path, data))
            return skill_discovery.scan_uploaded_folder(entries)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/skills/scan-known")
    async def scan_known_skills(request: KnownSkillScanRequest):
        try:
            return skill_discovery.scan_known(request.fallback_token)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    async def install_skill_through_core(source_kind: str, reference: dict):
        core_service, _, core_policy = get_core_runtime()
        call = CapabilityCall(
            capability_id="component.install",
            operation="install",
            project_root=str(Path(__file__).resolve().parent.parent),
            arguments={"source_kind": source_kind, "reference": reference},
        )
        core_policy.grant("user", "legacy", call, scope="project")
        task_id = str(uuid7())
        record = await core_service.submit(TaskCommand(
            command_id=str(uuid7()),
            task_id=task_id,
            thread_id=f"component:{source_kind}",
            project_id="legacy",
            command_type="component.install",
            payload=call.model_dump(mode="json"),
        ))
        if record.status is not TaskStatus.completed:
            failure = record.events[-1].payload
            code = failure.get("code")
            reason = failure.get("reason", "Component installation failed")
            status = 409 if code == "component_duplicate" else 422 if code in {"invalid_request", "component_probe_failed"} else 500
            raise HTTPException(status_code=status, detail=reason)
        completed = next(event for event in reversed(record.events) if event.event_type == "component.installed")
        return SkillPack.model_validate(completed.payload["result"])

    @application.post("/api/skills/install-discovery", status_code=201)
    async def install_discovered_skill(request: DiscoveryInstallRequest):
        try:
            installed = await install_skill_through_core("discovery", {"discovery_id": request.discovery_id})
            skillsets.reconcile()
            return installed
        except DuplicateSkillPack as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/skills/github/preview")
    async def preview_github_skill(request: GithubSkillPreviewRequest):
        try:
            return await asyncio.to_thread(github_skills.preview, request.url)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"Unable to download GitHub skill: {error}") from error

    @application.post("/api/skills/github/install", status_code=201)
    async def install_github_skill(request: GithubSkillInstallRequest):
        try:
            installed = await install_skill_through_core("github", {"preview_id": request.preview_id})
            skillsets.reconcile()
            return installed
        except DuplicateSkillPack as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.get("/api/skills/{pack_id}/{skill_id}/documentation.md")
    async def download_skill_documentation(pack_id: str, skill_id: str):
        try:
            document = skill_library.documentation(pack_id, skill_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Skill not found") from error
        return PlainTextResponse(
            document,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{skill_id}.md"'},
        )

    def convert_attachment(session_id: str, attachment_id: str):
        path, record = attachments.original_path(session_id, attachment_id)
        return skill_converter.convert(path, record.display_name)

    @application.post("/api/sessions/{session_id}/attachments/{attachment_id}/skill-preview")
    async def preview_skill_pack(session_id: str, attachment_id: str):
        try:
            return convert_attachment(session_id, attachment_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/sessions/{session_id}/attachments/{attachment_id}/skill-install", status_code=201)
    async def install_skill_pack(session_id: str, attachment_id: str):
        try:
            installed = await install_skill_through_core("attachment", {
                "session_id": session_id,
                "attachment_id": attachment_id,
            })
            skillsets.reconcile()
            return installed
        except DuplicateSkillPack as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/skills/deduplicate")
    async def deduplicate_skills():
        result = skill_library.deduplicate()
        for pack_id in result["removed_pack_ids"]:
            workspace.clear_skill_pack(pack_id)
        skillsets.reconcile()
        return result

    @application.patch("/api/sessions/{session_id}/skills")
    async def select_session_skills(session_id: str, request: SkillSelectionRequest):
        try:
            session = workspace.get_session(session_id)
            for selection in request.selected:
                if ":" not in selection:
                    raise ValueError("Invalid skill selection")
                skill = skill_library.get_skill(*selection.split(":", 1))
                if not skill.enabled:
                    raise ValueError("Disabled skills cannot be selected")
            session.selected_skill_ids = list(dict.fromkeys(request.selected))
            workspace.save_manifest(session)
            return session
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Skill or session not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.patch("/api/skills/{pack_id}/{skill_id}")
    async def update_skill(pack_id: str, skill_id: str, request: SkillUpdateRequest):
        try:
            updated = skill_library.update_skill(pack_id, skill_id, request.content, request.enabled)
            skillsets.reconcile()
            if request.session_id:
                session = workspace.get_session(request.session_id)
                selection = f"{pack_id}:{skill_id}"
                selected = [item for item in session.selected_skill_ids if item != selection]
                if request.enabled:
                    selected.append(selection)
                session.selected_skill_ids = selected
                workspace.save_manifest(session)
            return updated
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Skill or session not found") from error

    @application.patch("/api/skills/{pack_id}")
    async def rename_skill_pack(pack_id: str, request: SkillPackRenameRequest):
        try:
            return skill_library.rename(pack_id, request.name)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Skill pack not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.delete("/api/skills/{pack_id}", status_code=204)
    async def remove_skill_pack(pack_id: str):
        try:
            skill_library.remove(pack_id)
            workspace.clear_skill_pack(pack_id)
            skillsets.reconcile()
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Skill pack not found") from error
        return Response(status_code=204)

    @application.get("/api/sessions/{session_id}/artifacts/{filename}")
    async def download_artifact(session_id: str, filename: str):
        try:
            path = artifact_service.artifact_path(session_id, filename)
            return FileResponse(path, media_type="application/zip", filename=filename)
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Artifact not found") from error

    @application.get("/api/sessions/{session_id}/dependencies")
    async def detect_dependencies(session_id: str):
        try:
            return await asyncio.to_thread(dependency_service.detect, session_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error

    @application.patch("/api/sessions/{session_id}/attachments/{attachment_id}")
    async def update_attachment(session_id: str, attachment_id: str, request: AttachmentUpdate):
        try:
            return attachments.set_included(session_id, attachment_id, request.included)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error

    @application.delete("/api/sessions/{session_id}/attachments/{attachment_id}", status_code=204)
    async def delete_attachment(session_id: str, attachment_id: str):
        try:
            attachments.remove(session_id, attachment_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Attachment not found") from error
        return Response(status_code=204)

    def require_terminal_header(x_json_codr: str | None) -> None:
        if x_json_codr != "1":
            raise HTTPException(status_code=403, detail="Terminal request header required")

    async def github_call(operation: Callable[..., object], *args: object, **kwargs: object) -> object:
        try:
            return await asyncio.to_thread(operation, *args, **kwargs)
        except GitHubCLIError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.get("/api/github/status")
    async def github_status(x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.status)

    async def github_auth_call(operation: Callable[..., object], *args: object) -> object:
        try:
            return await asyncio.to_thread(operation, *args)
        except GitHubAuthSessionNotFound as error:
            raise HTTPException(status_code=404, detail="GitHub login session not found") from error
        except GitHubAuthSessionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @application.post("/api/github/auth/login")
    async def github_auth_login(
        request: GitHubAuthLoginRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_auth_call(github_auth.start)

    @application.get("/api/github/auth/login/{session_id}")
    async def github_auth_login_status(
        session_id: str,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_auth_call(github_auth.status, session_id)

    @application.post("/api/github/auth/login/{session_id}/cancel")
    async def github_auth_login_cancel(
        session_id: str,
        request: GitHubAuthCancelRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_auth_call(github_auth.cancel, session_id)

    @application.get("/api/github/repositories")
    async def github_repositories(x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.repositories)

    @application.post("/api/github/repositories", status_code=201)
    async def github_create_repository(
        request: GitHubRepositoryCreateRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.create_repository,
            request.name,
            request.description,
            request.private,
            request.auto_init,
            request.owner,
            request.homepage,
        )

    @application.patch("/api/github/repos/{owner}/{repository}")
    async def github_update_repository(
        owner: str,
        repository: str,
        request: GitHubRepositoryUpdateRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.update_repository,
            owner,
            repository,
            request.model_dump(exclude={"confirmed"}, exclude_none=True),
        )

    @application.delete("/api/github/repos/{owner}/{repository}")
    async def github_delete_repository(
        owner: str,
        repository: str,
        request: GitHubRepositoryDeleteRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        if request.confirm_name.casefold() != f"{owner}/{repository}".casefold():
            raise HTTPException(status_code=422, detail="Type the exact owner/repository name to confirm deletion")
        return await github_call(github_cli.delete_repository, owner, repository)

    @application.get("/api/github/repos/{owner}/{repository}/issues")
    async def github_issues(
        owner: str,
        repository: str,
        state: Literal["open", "closed", "all"] = "open",
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.issues, owner, repository, state)

    @application.post("/api/github/repos/{owner}/{repository}/issues", status_code=201)
    async def github_create_issue(
        owner: str,
        repository: str,
        request: GitHubIssueCreateRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.create_issue, owner, repository, request.title, request.body)

    @application.patch("/api/github/repos/{owner}/{repository}/issues/{number}")
    async def github_update_issue(
        owner: str,
        repository: str,
        number: int,
        request: GitHubIssueUpdateRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.update_issue, owner, repository, number,
            request.model_dump(exclude={"confirmed"}, exclude_none=True),
        )

    @application.post("/api/github/repos/{owner}/{repository}/issues/{number}/comments", status_code=201)
    async def github_comment_issue(
        owner: str,
        repository: str,
        number: int,
        request: GitHubIssueCommentRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.comment_issue, owner, repository, number, request.body)

    @application.get("/api/github/repos/{owner}/{repository}/pulls")
    async def github_pull_requests(
        owner: str,
        repository: str,
        state: Literal["open", "closed", "all"] = "open",
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.pull_requests, owner, repository, state)

    @application.get("/api/github/repos/{owner}/{repository}/branches")
    async def github_branches(
        owner: str,
        repository: str,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.branches, owner, repository)

    @application.post("/api/github/repos/{owner}/{repository}/branches", status_code=201)
    async def github_create_branch(
        owner: str,
        repository: str,
        request: GitHubRemoteBranchCreateRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.create_branch, owner, repository, request.branch, request.source_branch,
        )

    @application.delete("/api/github/repos/{owner}/{repository}/branches/{branch:path}")
    async def github_delete_branch(
        owner: str,
        repository: str,
        branch: str,
        request: GitHubConfirmedWrite,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.delete_branch, owner, repository, branch)

    @application.get("/api/github/repos/{owner}/{repository}/commits")
    async def github_commits(
        owner: str,
        repository: str,
        branch: str | None = None,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.commits, owner, repository, branch)

    @application.post("/api/github/repos/{owner}/{repository}/pulls", status_code=201)
    async def github_create_pull_request(
        owner: str,
        repository: str,
        request: GitHubPullRequestCreateRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.create_pull_request, owner, repository, request.head, request.base,
            request.title, request.body, request.draft,
        )

    @application.patch("/api/github/repos/{owner}/{repository}/pulls/{number}")
    async def github_update_pull_request(
        owner: str,
        repository: str,
        number: int,
        request: GitHubPullRequestUpdateRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.update_pull_request, owner, repository, number,
            request.model_dump(exclude={"confirmed"}, exclude_none=True),
        )

    @application.post("/api/github/repos/{owner}/{repository}/pulls/{number}/merge")
    async def github_merge_pull_request(
        owner: str,
        repository: str,
        number: int,
        request: GitHubPullRequestMergeRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.merge_pull_request, owner, repository, number, request.merge_method,
        )

    @application.get("/api/github/repos/{owner}/{repository}/releases")
    async def github_releases(
        owner: str,
        repository: str,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.releases, owner, repository)

    @application.post("/api/github/repos/{owner}/{repository}/releases", status_code=201)
    async def github_create_release(
        owner: str,
        repository: str,
        request: GitHubReleaseCreateRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.create_release, owner, repository, request.tag_name, request.name,
            request.body, request.target_commitish, request.draft, request.prerelease,
        )

    @application.patch("/api/github/repos/{owner}/{repository}/releases/{release_id}")
    async def github_update_release(
        owner: str,
        repository: str,
        release_id: int,
        request: GitHubReleaseUpdateRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.update_release,
            owner,
            repository,
            release_id,
            request.model_dump(exclude={"confirmed"}, exclude_none=True),
        )

    @application.delete("/api/github/repos/{owner}/{repository}/releases/{release_id}")
    async def github_delete_release(
        owner: str,
        repository: str,
        release_id: int,
        request: GitHubConfirmedWrite,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.delete_release, owner, repository, release_id)

    @application.post("/api/github/local/clone", status_code=201)
    async def github_local_clone(
        request: GitHubLocalCloneRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.clone_local_repository, request.repository, request.destination)

    @application.post("/api/github/local/fetch")
    async def github_local_fetch(
        request: GitHubLocalSyncRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.fetch_local_changes, request.project_root)

    @application.post("/api/github/local/pull")
    async def github_local_pull(
        request: GitHubLocalSyncRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.pull_local_changes, request.project_root)

    @application.post("/api/github/local/check-build")
    async def github_local_check_build(
        request: GitHubBuildCheckRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.check_build,
            request.project_root,
            request.repository,
            request.branch,
        )

    @application.post("/api/github/local/update-build")
    async def github_local_update_build(
        request: GitHubBuildUpdateRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(
            github_cli.update_build,
            request.project_root,
            request.repository,
            request.branch,
            request.expected_local_sha,
            request.expected_remote_sha,
            request.expected_login,
            request.expected_host,
        )

    @application.get("/api/github/local/status")
    async def github_local_status(
        project_root: str,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.local_status, project_root)

    @application.post("/api/github/local/branch", status_code=201)
    async def github_local_branch(
        request: GitHubLocalBranchRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.create_local_branch, request.project_root, request.branch)

    @application.post("/api/github/local/stage")
    async def github_local_stage(
        request: GitHubLocalStageRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.stage_local_files, request.project_root, request.paths)

    @application.post("/api/github/local/commit", status_code=201)
    async def github_local_commit(
        request: GitHubLocalCommitRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.commit_local_changes, request.project_root, request.message)

    @application.post("/api/github/local/push")
    async def github_local_push(
        request: GitHubLocalPushRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        return await github_call(github_cli.push_local_changes, request.project_root)

    @application.get("/api/coding-agents/status")
    async def coding_agent_status():
        return coding_agents.status()

    @application.get("/api/git-broker/status")
    async def git_broker_status(project_root: str):
        try:
            repository = await asyncio.to_thread(git_broker.inspect, project_root)
            return {"repository": repository, "grants": coding_agents.status()["grants"]}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/git-broker/grants", status_code=201)
    async def create_git_broker_grant(request: BrokerGrantRequest, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        try:
            return coding_agents.grant(request.project_root, request.profile)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.delete("/api/git-broker/grants/{grant_id}")
    async def revoke_git_broker_grant(grant_id: str, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        try:
            return coding_agents.revoke(grant_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Execution grant not found") from error

    async def execute_git_through_core(action_request, model: str, grant_id: str):
        core_service, _, _ = get_core_runtime()
        operation = next(
            (kind for kind in ("push", "commit", "sync") if any(action.kind == kind for action in action_request.actions)),
            "bounded_edit" if any(action.kind == "apply_patch" for action in action_request.actions) else "read",
        )
        call = CapabilityCall(
            capability_id="git.execute",
            operation=operation,
            project_root=action_request.project_root,
            arguments={
                "request": action_request.model_dump(mode="json"),
                "model": model,
                "grant_id": grant_id,
            },
        )
        task_id = str(uuid7())
        record = await core_service.submit(TaskCommand(
            command_id=str(uuid7()),
            task_id=task_id,
            thread_id=f"legacy:{task_id}",
            project_id="legacy",
            command_type="git.execute",
            payload=call.model_dump(mode="json"),
        ))
        if any(event.event_type == "task.permission_required" for event in record.events):
            raise PermissionError(f"Git {operation} requires explicit approval")
        if record.status is not TaskStatus.completed:
            raise RuntimeError(record.events[-1].payload.get("reason", "Git execution failed"))
        completed = next(event for event in reversed(record.events) if event.event_type == "git.completed")
        return completed.payload["result"]

    @application.post("/api/git-broker/tasks", status_code=201)
    async def execute_git_broker_task(request: BrokerTaskRequest, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        def authorized():
            return coding_agents.authorized_grant(request.grant_id, request.request.project_root, "broker")
        if not authorized():
            raise HTTPException(status_code=403, detail="Broker authorization does not cover this project")
        try:
            return await execute_git_through_core(request.request, request.model, request.grant_id)
        except (ValueError, RuntimeError, PermissionError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post("/api/git-broker/adapter", status_code=201)
    async def execute_git_broker_adapter(request: BrokerAdapterRunRequest, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        def authorized():
            return coding_agents.authorized_grant(request.grant_id, request.project_root, "broker")
        if not authorized():
            raise HTTPException(status_code=403, detail="Broker authorization does not cover this project")
        try:
            snapshot = await asyncio.to_thread(git_broker.inspect, request.project_root)
            contract = git_adapter.prompt_contract(snapshot.root, snapshot.dirty_fingerprint)
            response = await service.chat(request.model, f"{request.prompt}\n\n{contract}")
            action_request = git_adapter.parse(response.content)
            if Path(action_request.project_root).resolve() != Path(snapshot.root):
                raise ValueError("Model response changed the authorized project root")
            if action_request.baseline_fingerprint != snapshot.dirty_fingerprint:
                raise ValueError("Model response changed the authorized baseline")
            result = await execute_git_through_core(action_request, request.model, request.grant_id)
            return {"compatibility": "broker_adapter", "result": result}
        except (ValueError, RuntimeError, PermissionError, OllamaUnavailableError, ModelOutputError, ModelTimeoutError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    async def execute_project_workspace(project_root: str, model: str, outcome: str) -> dict:
        snapshot = await asyncio.to_thread(git_broker.inspect, project_root)
        contract = git_adapter.prompt_contract(snapshot.root, snapshot.dirty_fingerprint)
        generated = await service.chat(model, f"{outcome}\n\n{contract}")
        action_request = git_adapter.parse(generated.content)
        if Path(action_request.project_root).resolve() != Path(snapshot.root):
            raise ValueError("Model response changed the authorized project root")
        if action_request.baseline_fingerprint != snapshot.dirty_fingerprint:
            raise ValueError("Model response changed the authorized baseline")
        if any(action.kind not in {"status", "read"} for action in action_request.actions):
            raise PermissionError("Model-generated project effects require canonical task approval")
        result = await asyncio.to_thread(
            git_broker.execute,
            action_request,
            generated.model,
            "compatibility-read-only",
            lambda: True,
        )
        return {
            "route": "broker_adapter", "effective_model": generated.model,
            "project_root": snapshot.root, "result": asdict(result),
        }

    @application.post("/api/project-workspace/run", status_code=201)
    async def run_project_workspace(request: ProjectWorkspaceRunRequest, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        try:
            executed = await execute_project_workspace(request.project_root, request.model, request.outcome)
            return {**executed, "requested_model": request.model}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except (RuntimeError, PermissionError, OllamaUnavailableError, ModelOutputError, ModelTimeoutError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post("/api/workspace/tasks", response_model=WorkspaceTaskResponse, status_code=201)
    async def submit_workspace_task(request: WorkspaceTaskRequest, response: Response):
        if request.engine_id != "borg":
            raise HTTPException(status_code=409, detail="Requested engine is not a verified Workspace engine")
        try:
            session = workspace.get_session(request.session_id)
            installed = [
                item for item in await (inference_router.list_models() if inference_router else service.list_models())
                if item.get("installed")
            ]
            installed_names = [item["name"] for item in installed]
            if request.model_selection == "multi-model":
                run = await model_runs.create(ModelRunCreateRequest(
                    session_id=session.id, prompt=request.prompt, profile="general", parallelism=2,
                ))
                task = asyncio.create_task(model_runs.run(run.run_id))
                model_run_tasks.add(task)
                task.add_done_callback(finish_model_run)
                response.status_code = 202
                return WorkspaceTaskResponse(
                    task_id=run.run_id, requested_engine=request.engine_id, effective_engine="borg",
                    requested_model="multi-model", effective_model=None, route="multi-model",
                    status="running", warnings=[], result={"run_id": run.run_id},
                )
            if not installed_names:
                raise HTTPException(status_code=409, detail="No installed local model is available")
            warnings = []
            requested_model = request.model_selection
            selected_model = installed_names[0] if requested_model == "auto" else requested_model
            if selected_model not in installed_names:
                raise HTTPException(status_code=409, detail="Requested model is not installed")
            if requested_model == "auto":
                warnings.append(f"Auto selected {selected_model} from the installed model roster")
            compatibility = await service.tool_compatibility(selected_model)
            if not compatibility["available"]:
                raise HTTPException(status_code=409, detail="Requested engine and model do not have a verified tool route")
            effective_model = compatibility["effective_tool_model"] or selected_model
            if effective_model != selected_model:
                warnings.append(f"Verified tool execution uses {effective_model}; requested model remains {selected_model}")
            recommendation = recommendations.recommend(session, request.prompt)
            assembled = context_assembler.build(session, request.prompt, recommendation)
            core_service, _, _ = get_core_runtime()
            if core_projects is None:
                raise RuntimeError("project registry is unavailable")
            registered = core_projects.register(request.project_root)
            task_id = str(uuid7())
            route = compatibility.get("route") or "broker_verified"
            goal = GoalSpec(
                goal_id=f"goal:{task_id}", revision=1, objective=assembled.prompt,
                criteria=(CompletionCriterion(
                    criterion_id=f"criterion:{task_id}", kind=CriterionKind.project_state,
                    description="Complete the requested project work with fresh persisted evidence",
                ),), accepted=True,
            )
            record = await core_service.submit(TaskCommand(
                command_id=str(uuid7()), task_id=task_id,
                thread_id=f"workspace:{request.session_id}:{task_id}",
                project_id=registered.project_id, command_type="agent.run",
                payload={
                    "goal_spec": goal.model_dump(mode="json"), "target_path": ".",
                    "requested_model": selected_model, "effective_model": effective_model,
                    "route": route, "context_references": request.context_references,
                },
            ))
            awaiting_approval = any(
                event.event_type == "agent.approval_required" for event in record.events
            )
            status = "approval_required" if awaiting_approval else record.status.value
            if status not in {"completed", "failed", "cancelled"}:
                response.status_code = 202
            return WorkspaceTaskResponse(
                task_id=task_id, requested_engine=request.engine_id, effective_engine="borg",
                requested_model=requested_model, effective_model=effective_model,
                route=route, status=status, warnings=warnings,
                result={
                    "project_id": registered.project_id,
                    "task": record.model_dump(mode="json"),
                }, artifact_references=[],
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except (RuntimeError, PermissionError, OllamaUnavailableError, ModelOutputError, ModelTimeoutError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post("/api/coding-agents/grants", status_code=201)
    async def create_coding_agent_grant(request: CodingAgentGrantRequest, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        try:
            return coding_agents.grant(request.project_root, request.tool)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.delete("/api/coding-agents/grants/{grant_id}")
    async def revoke_coding_agent_grant(grant_id: str, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        try:
            return coding_agents.revoke(grant_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Coding agent grant not found") from error

    @application.post("/api/coding-agents/launch", status_code=201)
    async def launch_coding_agent(request: CodingAgentLaunchRequest, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        try:
            compatibility = await service.tool_compatibility(request.model)
            if not compatibility["available"]:
                raise RuntimeError("No verified tool-capable route is available")
            effective_model = compatibility["effective_tool_model"]
            fallback_used = compatibility["route"] == "delegated_verified"
            plan = coding_agents.launch_plan(
                request.tool, request.project_root, effective_model, request.mode, request.prompt,
                supports_tools=True,
            )
            terminal = terminals.create_agent(plan)
            terminal_payload = terminal if isinstance(terminal, dict) else terminal.__dict__
            return {
                **terminal_payload,
                "requested_model": request.model,
                "effective_model": effective_model,
                "tool_fallback_used": fallback_used,
                "tool_compatibility": compatibility,
            }
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/terminals")
    async def list_terminals():
        return terminals.list()

    @application.post("/api/terminals", status_code=201)
    async def create_terminal(request: TerminalCreateRequest, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        cwd = Path(request.cwd).resolve() if request.cwd else Path(__file__).resolve().parent.parent
        try:
            core_service, _, _ = get_core_runtime()
            call = CapabilityCall(
                capability_id="terminal.session",
                operation="session",
                project_root=str(cwd),
                arguments={"shell": request.shell},
            )
            task_id = str(uuid7())
            record = await core_service.submit(TaskCommand(
                command_id=str(uuid7()),
                task_id=task_id,
                thread_id=f"terminal:{task_id}",
                project_id="legacy",
                command_type="terminal.session",
                payload=call.model_dump(mode="json"),
            ))
            if record.events and record.events[-1].event_type == "task.permission_required":
                proposal_id = record.events[-1].payload.get("proposal_id")
                if not isinstance(proposal_id, str):
                    raise ValueError("Terminal session approval proposal is missing")
                # This endpoint is called from an explicit local terminal action; consume only its exact one-shot proposal.
                record = await core_service.approve(
                    task_id, principal="user", scope="project", proposal_id=proposal_id,
                )
            if record.status is not TaskStatus.completed:
                reason = record.events[-1].payload.get("reason") if record.events else None
                raise ValueError(reason or "Terminal creation failed")
            started = next(event for event in reversed(record.events) if event.event_type == "terminal.session_started")
            return started.payload["record"]
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    async def submit_terminal_mutation(operation: str, terminal_id: str) -> None:
        core_service, _, _ = get_core_runtime()
        call = CapabilityCall(
            capability_id=f"terminal.{operation}",
            operation=operation,
            project_root=str(Path(__file__).resolve().parent.parent),
            arguments={"terminal_id": terminal_id},
        )
        task_id = str(uuid7())
        record = await core_service.submit(TaskCommand(
            command_id=str(uuid7()),
            task_id=task_id,
            thread_id=f"terminal:{terminal_id}",
            project_id="legacy",
            command_type=f"terminal.{operation}",
            payload=call.model_dump(mode="json"),
        ))
        if record.events and record.events[-1].event_type == "task.permission_required":
            proposal_id = record.events[-1].payload.get("proposal_id")
            if not isinstance(proposal_id, str):
                raise HTTPException(status_code=409, detail="Terminal operation approval proposal is missing")
            try:
                record = await core_service.approve(
                    task_id, principal="user", scope="project", proposal_id=proposal_id,
                )
            except PermissionError as error:
                raise HTTPException(status_code=403, detail=str(error)) from error
        if record.status is not TaskStatus.completed:
            reason = record.events[-1].payload.get("reason", "Terminal operation failed") if record.events else "Terminal operation failed"
            if reason == "capability target not found":
                raise HTTPException(status_code=404, detail="Terminal not found")
            raise HTTPException(status_code=409, detail=reason)

    @application.post("/api/terminals/{terminal_id}/interrupt", status_code=204)
    async def interrupt_terminal(terminal_id: str, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        await submit_terminal_mutation("interrupt", terminal_id)
        return Response(status_code=204)

    @application.delete("/api/terminals/{terminal_id}", status_code=204)
    async def close_terminal(terminal_id: str, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        await submit_terminal_mutation("close", terminal_id)
        return Response(status_code=204)

    def validate_action_terminal(proposal, terminal_id: str):
        try:
            terminal = terminals.get(terminal_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Terminal not found") from error
        if Path(terminal.cwd).resolve() != Path(proposal.cwd).resolve():
            raise HTTPException(status_code=400, detail="Proposal working directory must match the terminal")
        return terminal

    @application.post("/api/sessions/{session_id}/action-proposals/{proposal_id}/approve")
    async def approve_action(
        session_id: str,
        proposal_id: str,
        request: ActionApprovalRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        try:
            proposal = action_proposals.get(session_id, proposal_id)
            validate_action_terminal(proposal, request.terminal_id)
            return action_proposals.approve(session_id, proposal_id, request.terminal_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Action proposal not found") from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @application.post("/api/sessions/{session_id}/action-proposals/{proposal_id}/confirm-destructive")
    async def confirm_destructive_action(
        session_id: str,
        proposal_id: str,
        request: DestructiveConfirmationRequest,
        x_json_codr: str | None = Header(None),
    ):
        require_terminal_header(x_json_codr)
        try:
            proposal = action_proposals.get(session_id, proposal_id)
            validate_action_terminal(proposal, request.terminal_id)
            return action_proposals.confirm_destructive(
                session_id, proposal_id, request.terminal_id, request.phrase
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Action proposal not found") from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @application.post("/api/sessions/{session_id}/action-proposals/{proposal_id}/reject")
    async def reject_action(session_id: str, proposal_id: str):
        try:
            return action_proposals.reject(session_id, proposal_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Action proposal not found") from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @application.websocket("/ws/terminals/{terminal_id}")
    async def terminal_socket(websocket: WebSocket, terminal_id: str):
        expected_origin = f"http://{websocket.url.hostname}:{websocket.url.port}"
        if websocket.headers.get("origin") != expected_origin:
            await websocket.close(code=1008)
            return
        try:
            terminals.get(terminal_id)
        except KeyError:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        pending_action_markers: dict[str, str] = {}
        completion_tail = ""
        try:
            output_sequence = max(0, int(websocket.query_params.get("after_seq", "0")))
        except ValueError:
            output_sequence = 0

        async def send_output():
            nonlocal completion_tail, output_sequence
            while True:
                events = await asyncio.to_thread(terminals.read_after, terminal_id, output_sequence, 0.2)
                for sequence, output in events:
                    await websocket.send_json({"type": "output", "seq": sequence, "data": output})
                    output_sequence = sequence
                    completion_tail = (completion_tail + output)[-2048:]
                    for marker, proposal_id in list(pending_action_markers.items()):
                        match = re.search(re.escape(marker) + r"(-?\d+)", completion_tail)
                        if match:
                            exit_code = int(match.group(1))
                            await websocket.send_json({
                                "type": "action_completed",
                                "proposal_id": proposal_id,
                                "success": exit_code == 0,
                                "exit_code": exit_code,
                            })
                            pending_action_markers.pop(marker, None)
                if terminals.get(terminal_id).status != "running" and not events:
                    break
            await websocket.send_json({"type": "exit", "last_seq": output_sequence})

        async def receive_input():
            nonlocal output_sequence
            try:
                while True:
                    message = await websocket.receive_json()
                    if message.get("type") == "input":
                        terminals.write(terminal_id, str(message.get("data", "")))
                    elif message.get("type") == "attach":
                        output_sequence = max(output_sequence, int(message.get("after_seq", 0)))
                    elif message.get("type") == "resize":
                        try:
                            terminals.resize(terminal_id, int(message.get("cols", 0)), int(message.get("rows", 0)))
                        except (TypeError, ValueError) as error:
                            await websocket.send_json({"type": "protocol_error", "error": str(error)})
                    elif message.get("type") == "interrupt":
                        terminals.interrupt(terminal_id)
                    elif message.get("type") == "approved_action":
                        proposal_id = str(message.get("proposal_id", ""))
                        marker = f"__JSON_CODR_ACTION_DONE__:{proposal_id}:"
                        pending_action_markers[marker] = proposal_id
                        try:
                            terminals.write_approved(
                                terminal_id,
                                action_proposals,
                                proposal_id,
                                str(message.get("token", "")),
                                completion_marker=marker,
                            )
                            await websocket.send_json({"type": "action_started", "proposal_id": proposal_id})
                        except (KeyError, PermissionError, RuntimeError) as error:
                            pending_action_markers.pop(marker, None)
                            await websocket.send_json({
                                "type": "action_error",
                                "proposal_id": proposal_id,
                                "error": str(error),
                            })
            except WebSocketDisconnect:
                return

        sender = asyncio.create_task(send_output())
        receiver = asyncio.create_task(receive_input())
        try:
            done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
        except WebSocketDisconnect:
            pass

    async def generate_chat_through_core(
        model: str,
        prompt: str,
        images: list[Path],
        thread_id: str,
        session_id: str | None = None,
    ) -> ChatResult:
        core_service, _, _ = get_core_runtime()
        call = CapabilityCall(
            capability_id="inference.generate",
            operation="generate",
            project_root=str(Path(__file__).resolve().parent.parent),
            arguments={
                "model": model,
                "prompt": prompt,
                "images": [str(path) for path in images],
                **({"session_id": session_id} if session_id else {}),
            },
        )
        task_id = str(uuid7())
        record = await core_service.submit(TaskCommand(
            command_id=str(uuid7()),
            task_id=task_id,
            thread_id=thread_id,
            project_id="legacy",
            command_type="inference.generate",
            payload=call.model_dump(mode="json"),
        ))
        if record.status is not TaskStatus.completed:
            failure = record.events[-1].payload
            code = failure.get("code")
            reason = failure.get("reason", "Model request failed")
            status = {"model_timeout": 504, "model_output": 502, "invalid_request": 400}.get(code, 502)
            if code == "model_unavailable":
                status = 409 if reason == "Model is not installed" else 502
                if status == 502:
                    hardware.record_runtime_failure(reason)
            raise HTTPException(status_code=status, detail=reason)
        completed = next(event for event in reversed(record.events) if event.event_type == "inference.completed")
        return ChatResult.model_validate(completed.payload["result"])

    @application.post("/api/ag-ui/run")
    async def run_agui(run_input: RunAgentInput, http_request: Request):
        try:
            prompt = build_agui_prompt(run_input)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        forwarded_props = run_input.forwarded_props
        requested_model = (
            forwarded_props.get("model")
            if isinstance(forwarded_props, dict)
            else None
        )
        if requested_model is None:
            requested_model = getattr(service, "config", {}).get("model")
        if not isinstance(requested_model, str) or not requested_model.strip() or len(requested_model) > 200:
            raise HTTPException(
                status_code=422,
                detail="Set a configured model or pass forwardedProps.model",
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in requested_model):
            raise HTTPException(status_code=422, detail="Invalid model name")
        encoder = EventEncoder(accept=http_request.headers.get("accept"))
        backend = inference_router or service
        return StreamingResponse(
            stream_agui_events(
                run_input,
                model=requested_model.strip(),
                prompt=prompt,
                backend=backend,
                encoder=encoder,
            ),
            media_type=encoder.get_content_type(),
            headers={"Cache-Control": "no-cache"},
        )

    @application.post("/api/chat", response_model=ChatResult)
    async def chat(request: ChatRequest, http_request: Request):
        if not request.prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt must not be empty")
        try:
            original_prompt = request.prompt.strip()
            model_prompt = original_prompt
            model_images = []
            context_result = None
            recommendation_result = None
            if request.session_id:
                session = workspace.get_session(request.session_id)
                recommendation_result = recommendations.recommend(session, original_prompt)
                context_result = context_assembler.build(session, original_prompt, recommendation_result)
                model_prompt = context_result.prompt
                if await service.supports_vision(request.model):
                    model_images = context_assembler.image_paths(session)
            conversion_words = ("convert", "save", "archive")
            wants_conversion = all(word in original_prompt.casefold() for word in conversion_words)
            source_archive = next(
                (
                    item for item in (session.attachments if request.session_id else [])
                    if item.included and item.detected_type in {"application/zip", "application/x-7z-compressed"}
                ),
                None,
            )
            if wants_conversion and source_archive:
                model_prompt = canonical_model_prompt(
                    model=request.model,
                    task=original_prompt,
                    assembled_prompt=model_prompt,
                )
                bundle = await service.convert_archive(request.model, model_prompt)
                artifact = artifact_service.save_conversion(
                    request.session_id,
                    source_archive.display_name,
                    bundle.files,
                )
                artifact.url = str(
                    http_request.url_for(
                        "download_artifact",
                        session_id=request.session_id,
                        filename=artifact.filename,
                    )
                )
                result = ChatResult(
                    model=request.model,
                    status="success",
                    summary=bundle.summary,
                    content=(
                        f"Converted files: {len(bundle.files)}\n"
                        f"Saved archive: {artifact.filename}\n"
                        f"Hard drive: {artifact.path}\n"
                        f"Download URL: {artifact.url}"
                    ),
                    artifact=artifact,
                )
            else:
                result = await generate_chat_through_core(
                    request.model,
                    original_prompt,
                    model_images,
                    request.session_id or f"chat:{uuid7()}",
                    request.session_id,
                )
            if context_result and recommendation_result:
                result.attached_skills = context_result.attached_skills
                result.attached_skillsets = context_result.skillsets
                result.skill_recommendations = recommendation_result.recommendations
            if request.session_id and result.actions:
                source_skills = [item.reference for item in (context_result.attached_skills if context_result else [])]
                result.action_proposals = action_proposals.propose(
                    request.session_id,
                    result.actions,
                    source_skills,
                    str(Path(__file__).resolve().parent.parent),
                )
            if request.session_id:
                canonical_run = model_runs.record_single(
                    session_id=request.session_id,
                    prompt=original_prompt,
                    requested_model=request.model,
                    result=result,
                )
                result.run_id = canonical_run.run_id
                workspace.append_message(
                    request.session_id,
                    ChatMessage(role="user", content=original_prompt, task_id=canonical_run.run_id),
                )
                workspace.append_message(
                    request.session_id,
                    ChatMessage(
                        role="assistant",
                        content=f"{result.summary}\n\n{result.content}",
                        task_id=canonical_run.run_id,
                    ),
                )
            return result
        except InvalidSessionId as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Session not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ModelTimeoutError as error:
            raise HTTPException(status_code=504, detail=str(error)) from error
        except ModelOutputError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except OllamaUnavailableError as error:
            status = 409 if str(error) == "Model is not installed" else 502
            if status == 502:
                hardware.record_runtime_failure(str(error))
            raise HTTPException(status_code=status, detail=str(error)) from error

    return application


app = create_app(OllamaService(), optimized=True)
