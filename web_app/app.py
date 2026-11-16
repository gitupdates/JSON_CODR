from pathlib import Path

import asyncio
import re
import sys

from fastapi import FastAPI, File, Header, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from web_app.attachments import AttachmentService, AttachmentTooLarge
from web_app.actions import ActionProposalService
from web_app.artifacts import ArtifactService
from web_app.context import ContextAssembler
from web_app.hardware import HardwareBackendManager
from web_app.inference.catalog import OptimizedModelCatalog
from web_app.inference.contracts import ProviderKind
from web_app.inference.detection import AcceleratorDetector
from web_app.inference.environments import EnvironmentManager
from web_app.inference.providers.registry import ProviderRegistry
from web_app.inference.router import InferenceRouter
from web_app.inference.sidecar import SidecarClient
from web_app.inference.compatibility import ollama_model_status, optimized_model_status
from web_app.inference.search import OptimizedModelSearch
from web_app.localperf.package import LocalPerfPackageError, LocalPerfPackageService
from web_app.localperf.storage import LocalPerfStorage
from web_app.integrity_benchmark import IntegrityBenchmarkService
from web_app.benchmark_baseline import BenchmarkBaselineService
from web_app.coding_agents import CodingAgentService
from web_app.git_broker import GitBrokerService
from web_app.git_adapter import GitActionAdapter
from web_app.dependencies import DependencyService
from web_app.models import ActionApprovalRequest, ActionSuggestion, AttachmentUpdate, BrokerAdapterRunRequest, BrokerGrantRequest, BrokerTaskRequest, ChatMessage, ChatRequest, ChatResult, ClipboardTextRequest, CodingAgentGrantRequest, CodingAgentLaunchRequest, DestructiveConfirmationRequest, DiscoveryInstallRequest, GpuProfileSettings, HardwareBenchmarkRequest, HardwareProbeRequest, IntegrityBenchmarkRequest, KnownSkillScanRequest, SessionSkillRoutingUpdate, SettingsUpdate, SkillPackRenameRequest, SkillRecommendationRequest, SkillScanRequest, SkillSelectionRequest, SkillUpdateRequest, TerminalCreateRequest
from web_app.ollama_service import (
    ModelOutputError,
    ModelTimeoutError,
    OllamaService,
    OllamaUnavailableError,
)
from web_app.workspace import InvalidSessionId, WorkspaceService, default_data_root
from web_app.terminal import TerminalService
from web_app.skills import DuplicateSkillPack, SkillConverterService, SkillDiscoveryService, SkillLibraryService
from web_app.settings import SettingsService
from web_app.skillsets import SkillsetService
from web_app.recommendations import SkillRecommendationService
from web_app.version import APP_VERSION


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
) -> FastAPI:
    application = FastAPI(title="JSON_CODR", version=APP_VERSION)
    workspace = workspace or WorkspaceService(default_data_root())
    attachments = attachments or AttachmentService(workspace)
    skill_library = SkillLibraryService(workspace.data_root)
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
    context_assembler = ContextAssembler(attachments, skills=skill_library)
    dependency_service = DependencyService(attachments)
    artifact_service = ArtifactService(workspace)
    terminals = terminals or TerminalService()
    close_terminals = getattr(terminals, "close_all", None)
    if close_terminals is not None:
        application.router.add_event_handler("shutdown", close_terminals)
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
        matrix = []
        for candidate in detected:
            backend = candidate["id"]
            if backend in {"cpu", "ollama_gpu"} or backend.startswith(("cuda_", "rocm_", "vulkan")):
                models = [ollama_model_status(name, backend, running, bool(candidate.get("compatible"))) for name in installed_names]
            else:
                models = []
                for model in catalog.list():
                    if model.provider.value != backend:
                        continue
                    installed_model = environment_manager.model_path(model).is_dir()
                    verified = bool(inference_router and model.id in inference_router.verified_models)
                    models.append(optimized_model_status(model, installed_model, bool(candidate.get("runtime_ready")), verified))
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
    async def upload_attachment(session_id: str, file: UploadFile = File(...)):
        try:
            return attachments.import_stream(session_id, file.filename or "attachment", file.file)
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

    @application.post("/api/skills/scan-known")
    async def scan_known_skills(request: KnownSkillScanRequest):
        try:
            return skill_discovery.scan_known(request.fallback_token)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/skills/install-discovery", status_code=201)
    async def install_discovered_skill(request: DiscoveryInstallRequest):
        try:
            installed = skill_discovery.install(request.discovery_id)
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
            installed = skill_library.install(convert_attachment(session_id, attachment_id))
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

    @application.post("/api/git-broker/tasks", status_code=201)
    async def execute_git_broker_task(request: BrokerTaskRequest, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        def authorized():
            return coding_agents.authorized_grant(request.grant_id, request.request.project_root, "broker")
        if not authorized():
            raise HTTPException(status_code=403, detail="Broker authorization does not cover this project")
        try:
            return await asyncio.to_thread(
                git_broker.execute, request.request, request.model, request.grant_id, authorized
            )
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
            result = await asyncio.to_thread(
                git_broker.execute, action_request, request.model, request.grant_id, authorized
            )
            return {"compatibility": "broker_adapter", "result": result}
        except (ValueError, RuntimeError, PermissionError, OllamaUnavailableError, ModelOutputError, ModelTimeoutError) as error:
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
            plan = coding_agents.launch_plan(
                request.tool, request.project_root, request.model, request.mode, request.prompt
            )
            return terminals.create_agent(plan)
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
            return terminals.create(request.shell, cwd)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/terminals/{terminal_id}/interrupt", status_code=204)
    async def interrupt_terminal(terminal_id: str, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        try:
            terminals.interrupt(terminal_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Terminal not found") from error
        return Response(status_code=204)

    @application.delete("/api/terminals/{terminal_id}", status_code=204)
    async def close_terminal(terminal_id: str, x_json_codr: str | None = Header(None)):
        require_terminal_header(x_json_codr)
        try:
            terminals.close(terminal_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Terminal not found") from error
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
                result = await (
                    inference_router.chat(request.model, model_prompt, images=model_images)
                    if inference_router else service.chat(request.model, model_prompt, images=model_images)
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
                workspace.append_message(request.session_id, ChatMessage(role="user", content=original_prompt))
                workspace.append_message(
                    request.session_id,
                    ChatMessage(role="assistant", content=f"{result.summary}\n\n{result.content}"),
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
