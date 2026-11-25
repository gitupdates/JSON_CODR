from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_POLICY_VERSION = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$")


class ModelPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class CodingProbe:
    prompt: str
    expected: str
    timeout_seconds: int
    maximum_tokens: int


@dataclass(frozen=True)
class ReviewedModel:
    name: str
    digest: str
    purpose: str
    maximum_download_bytes: int


@dataclass(frozen=True)
class ModelSelectionEvidence:
    policy_version: str
    model: str
    digest: str
    probe_passed: bool
    probe_detail: str
    fallback_reason: str | None

    def to_document(self) -> dict[str, object]:
        return asdict(self)


Probe = Callable[[str, CodingProbe], bool | Mapping[str, object]]


class ModelPolicy:
    def __init__(
        self,
        *,
        policy_version: str,
        probe: CodingProbe,
        models: Sequence[ReviewedModel],
    ) -> None:
        self.policy_version = policy_version
        self.probe = probe
        self.models = tuple(models)

    @classmethod
    def load(cls, path: str | Path) -> ModelPolicy:
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ModelPolicyError(f"model policy is unreadable: {error}") from error
        return cls.from_document(document)

    @classmethod
    def from_document(cls, document: object) -> ModelPolicy:
        if not isinstance(document, Mapping) or document.get("schema_version") != "2":
            raise ModelPolicyError("model policy requires schema_version 2")
        policy_version = document.get("policy_version")
        if not isinstance(policy_version, str) or not _POLICY_VERSION.fullmatch(policy_version):
            raise ModelPolicyError("model policy version is invalid")
        probe_value = document.get("probe")
        if not isinstance(probe_value, Mapping):
            raise ModelPolicyError("model policy coding probe is missing")
        probe = CodingProbe(
            prompt=_required_text(probe_value, "prompt"),
            expected=_required_text(probe_value, "expected"),
            timeout_seconds=_bounded_integer(probe_value, "timeout_seconds", minimum=1, maximum=120),
            maximum_tokens=_bounded_integer(probe_value, "maximum_tokens", minimum=1, maximum=128),
        )
        raw_models = document.get("models")
        if not isinstance(raw_models, list) or len(raw_models) < 2:
            raise ModelPolicyError("model policy requires a preferred model and at least one fallback")
        models: list[ReviewedModel] = []
        names: set[str] = set()
        for value in raw_models:
            if not isinstance(value, Mapping):
                raise ModelPolicyError("model policy contains an invalid model")
            name = _required_text(value, "name")
            digest = _normalize_digest(_required_text(value, "digest"))
            purpose = _required_text(value, "purpose")
            if purpose != "reviewed local coding":
                raise ModelPolicyError(f"model {name} is not approved for reviewed local coding")
            if name in names:
                raise ModelPolicyError(f"model policy contains duplicate model name: {name}")
            names.add(name)
            models.append(ReviewedModel(
                name=name,
                digest=digest,
                purpose=purpose,
                maximum_download_bytes=_bounded_integer(
                    value, "maximum_download_bytes", minimum=1, maximum=20_000_000_000
                ),
            ))
        return cls(policy_version=policy_version, probe=probe, models=models)

    def reviewed_model(self, name: str) -> ReviewedModel | None:
        return next((model for model in self.models if model.name == name), None)

    def require_installed_digest(
        self, name: str, installed_models: Sequence[Mapping[str, object]]
    ) -> str:
        reviewed = self.reviewed_model(name)
        if reviewed is None:
            raise ModelPolicyError(f"model is not reviewed by policy {self.policy_version}: {name}")
        installed = _installed_by_name(installed_models).get(name)
        if installed is None:
            raise ModelPolicyError(f"reviewed model is not installed: {name}")
        digest = _installed_digest(installed, name)
        if digest != reviewed.digest:
            raise ModelPolicyError(
                f"reviewed model digest drift for {name}: expected {reviewed.digest}, installed {digest}"
            )
        return digest

    def select(
        self,
        installed_models: Sequence[Mapping[str, object]],
        *,
        probe: Probe,
    ) -> ModelSelectionEvidence:
        installed = _installed_by_name(installed_models)
        rejections: list[str] = []
        for model in self.models:
            record = installed.get(model.name)
            if record is None:
                rejections.append(f"{model.name} is not installed")
                continue
            try:
                digest = _installed_digest(record, model.name)
            except ModelPolicyError as error:
                rejections.append(str(error))
                continue
            if digest != model.digest:
                rejections.append(
                    f"{model.name} digest drift: expected {model.digest}, installed {digest}"
                )
                continue
            try:
                probe_value = probe(model.name, self.probe)
                if isinstance(probe_value, Mapping):
                    passed = probe_value.get("passed") is True
                    detail_value = probe_value.get("detail")
                    detail = str(detail_value) if detail_value else (
                        "coding probe passed" if passed else "coding probe failed"
                    )
                else:
                    passed = probe_value is True
                    detail = "coding probe passed" if passed else "coding probe failed"
            except Exception as error:
                passed = False
                detail = f"coding probe failed: {type(error).__name__}"
            if not passed:
                rejections.append(f"{model.name} probe rejected: {detail}")
                continue
            return ModelSelectionEvidence(
                policy_version=self.policy_version,
                model=model.name,
                digest=model.digest,
                probe_passed=True,
                probe_detail=detail,
                fallback_reason="; ".join(rejections) if rejections else None,
            )
        reason = "; ".join(rejections) or "no reviewed candidates were evaluated"
        raise ModelPolicyError(f"no reviewed coding model passed policy: {reason}")


def _required_text(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise ModelPolicyError(f"model policy requires {field}")
    return item.strip()


def _bounded_integer(
    value: Mapping[str, object], field: str, *, minimum: int, maximum: int
) -> int:
    item = value.get(field)
    if isinstance(item, bool) or not isinstance(item, int) or not minimum <= item <= maximum:
        raise ModelPolicyError(f"model policy {field} must be between {minimum} and {maximum}")
    return item


def _normalize_digest(value: str) -> str:
    digest = value.casefold()
    if not digest.startswith("sha256:"):
        digest = f"sha256:{digest}"
    if not _DIGEST.fullmatch(digest):
        raise ModelPolicyError(f"invalid Ollama digest: {value}")
    return digest


def _installed_by_name(
    installed_models: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    installed: dict[str, Mapping[str, object]] = {}
    for record in installed_models:
        name = record.get("name")
        if isinstance(name, str) and name and name not in installed:
            installed[name] = record
    return installed


def _installed_digest(record: Mapping[str, object], name: str) -> str:
    value = record.get("digest")
    if not isinstance(value, str) or not value:
        raise ModelPolicyError(f"installed model has no digest: {name}")
    return _normalize_digest(value)


def _loopback_endpoint(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ModelPolicyError("Ollama policy evaluation requires a plain loopback HTTP origin")
    return value.rstrip("/")


def _local_json(endpoint: str, path: str, *, payload: Mapping[str, object] | None, timeout: int) -> Any:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{endpoint}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def evaluate_local_policy(policy: ModelPolicy, endpoint: str) -> ModelSelectionEvidence:
    origin = _loopback_endpoint(endpoint)
    tags = _local_json(origin, "/api/tags", payload=None, timeout=5)
    if not isinstance(tags, Mapping) or not isinstance(tags.get("models"), list):
        raise ModelPolicyError("Ollama returned a malformed model inventory")

    def probe(model: str, spec: CodingProbe) -> Mapping[str, object]:
        payload = {
            "model": model,
            "prompt": spec.prompt,
            "stream": False,
            "format": "json",
            "keep_alive": "5m",
            "options": {
                "temperature": 0,
                "num_predict": spec.maximum_tokens,
                "num_ctx": 1024,
            },
        }
        deadline = time.monotonic() + spec.timeout_seconds
        result: Any = None
        for attempt, delay in enumerate((0.0, 0.5, 1.0)):
            if delay:
                remaining = deadline - time.monotonic()
                if remaining <= delay:
                    break
                time.sleep(delay)
            try:
                result = _local_json(
                    origin,
                    "/api/generate",
                    payload=payload,
                    timeout=max(1, int(deadline - time.monotonic())),
                )
                break
            except (HTTPError, URLError, ConnectionResetError, TimeoutError):
                if attempt == 2 or time.monotonic() >= deadline:
                    raise
        response = result.get("response") if isinstance(result, Mapping) else None
        try:
            structured = json.loads(response) if isinstance(response, str) else None
        except json.JSONDecodeError:
            structured = None
        passed = isinstance(structured, Mapping) and structured.get("status") == spec.expected
        return {
            "passed": passed,
            "detail": (
                "structured coding probe passed"
                if passed
                else "coding probe did not return the required structured status"
            ),
        }

    return policy.select(tags["models"], probe=probe)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="json-codr-model-policy")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    args = parser.parse_args(argv)
    try:
        policy = ModelPolicy.load(args.policy)
        evidence = evaluate_local_policy(policy, args.endpoint)
        document = {
            "state": "ready",
            "detail": "A reviewed digest-bound coding model passed its local capability probe.",
            **evidence.to_document(),
        }
        code = 0
    except Exception as error:
        document = {
            "state": "action-required",
            "detail": str(error),
            "policy_version": None,
            "model": None,
            "digest": None,
            "probe_passed": False,
            "probe_detail": "coding probe did not pass",
            "fallback_reason": str(error),
        }
        code = 10
    print(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
