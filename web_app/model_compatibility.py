from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


_INCOMPATIBLE_MARKERS = (
    "ggml_assert",
    "failed to load model",
    "error loading model",
    "llama-server process has terminated",
    "model runner has unexpectedly stopped",
    "unsupported architecture",
)
_CAPABILITY_MARKERS = (
    "does not support thinking",
    "does not support tools",
    "does not support format",
    "unsupported format",
    "invalid option",
    "unknown field",
)
_TRANSIENT_MARKERS = (
    "connection reset",
    "connection refused",
    "forcibly closed",
    "temporarily unavailable",
    "timed out",
    "timeout",
)
_FAILED_STATUSES = frozenset({"quarantined", "failed"})


class ModelCompatibilityConfigError(ValueError):
    pass


class ModelCompatibilityLayer:
    """Policy and digest-bound evidence for local model compatibility.

    The layer does not make network requests. Callers supply Ollama's live
    inventory and record evidence only after a real inference attempt.
    """

    def __init__(
        self,
        *,
        base_fallback_order: tuple[str, ...],
        model_rules: dict[str, dict[str, object]],
        state_path: Path,
        state: dict[str, dict[str, str]],
    ) -> None:
        self.base_fallback_order = base_fallback_order
        self.model_rules = model_rules
        self.state_path = state_path
        self._state = state

    @classmethod
    def load(cls, config_path: Path, state_path: Path) -> "ModelCompatibilityLayer":
        try:
            payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ModelCompatibilityConfigError("unable to read model compatibility policy") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ModelCompatibilityConfigError("unsupported model compatibility policy schema")
        base_fallback_order = cls._model_names(payload.get("base_fallback_order"), "base_fallback_order")
        raw_rules = payload.get("models", {})
        if not isinstance(raw_rules, dict):
            raise ModelCompatibilityConfigError("model compatibility rules must be an object")
        model_rules: dict[str, dict[str, object]] = {}
        for requested, raw_rule in raw_rules.items():
            if not isinstance(requested, str) or not requested.strip() or not isinstance(raw_rule, dict):
                raise ModelCompatibilityConfigError("model compatibility rule is malformed")
            alternates = cls._model_names(raw_rule.get("alternates", []), f"alternates for {requested}")
            prefer_alternate = raw_rule.get("prefer_alternate", False)
            reason = raw_rule.get("reason", "")
            if not isinstance(prefer_alternate, bool) or not isinstance(reason, str):
                raise ModelCompatibilityConfigError(f"model compatibility rule for {requested} is malformed")
            model_rules[requested] = {
                "alternates": alternates,
                "prefer_alternate": prefer_alternate,
                "reason": reason.strip()[:1000],
            }
        return cls(
            base_fallback_order=base_fallback_order,
            model_rules=model_rules,
            state_path=Path(state_path),
            state=cls._read_state(Path(state_path)),
        )

    @staticmethod
    def _model_names(value: object, field: str) -> tuple[str, ...]:
        if not isinstance(value, list):
            raise ModelCompatibilityConfigError(f"{field} must be a list")
        result: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ModelCompatibilityConfigError(f"{field} contains an invalid model name")
            name = item.strip()
            if name not in result:
                result.append(name)
        return tuple(result)

    @staticmethod
    def _read_state(path: Path) -> dict[str, dict[str, str]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return {}
        models = payload.get("models")
        if not isinstance(models, dict):
            return {}
        result: dict[str, dict[str, str]] = {}
        for name, record in models.items():
            if not isinstance(name, str) or not isinstance(record, dict):
                return {}
            digest = record.get("digest")
            status = record.get("status")
            profile = record.get("profile")
            error = record.get("error", "")
            updated_at = record.get("updated_at", "")
            if (
                not isinstance(digest, str)
                or status not in {"compatible", "quarantined", "failed", "transient_error", "capability_limited"}
                or not isinstance(profile, str)
                or not isinstance(error, str)
                or not isinstance(updated_at, str)
            ):
                return {}
            result[name] = {
                "digest": digest,
                "status": status,
                "profile": profile,
                "error": error[:1000],
                "updated_at": updated_at,
            }
        return result

    @staticmethod
    def _live_by_name(live: Mapping[str, Mapping[str, object]] | Sequence[Mapping[str, object]]) -> dict[str, dict]:
        records = live.values() if isinstance(live, Mapping) else live
        result: dict[str, dict] = {}
        for item in records:
            if not isinstance(item, Mapping):
                continue
            name = item.get("model") or item.get("name")
            if isinstance(name, str) and name:
                result[name] = dict(item)
        return result

    @staticmethod
    def digest(item: Mapping[str, object] | None) -> str:
        if not item:
            return ""
        digest = item.get("digest")
        return str(digest) if isinstance(digest, str) else ""

    def _specific_names(self, requested: str) -> tuple[str, ...]:
        rule = self.model_rules.get(requested, {})
        alternates = tuple(rule.get("alternates", ()))
        if rule.get("prefer_alternate"):
            return (*alternates, requested)
        return (requested, *alternates)

    def _matching_state(self, model: str, digest: str) -> dict[str, str] | None:
        record = self._state.get(model)
        if record is None or record.get("digest", "") != digest:
            return None
        return record

    def _blocked(self, model: str, item: Mapping[str, object]) -> bool:
        state = self._matching_state(model, self.digest(item))
        return state is not None and state.get("status") in _FAILED_STATUSES

    def candidates(
        self,
        requested: str,
        live: Mapping[str, Mapping[str, object]] | Sequence[Mapping[str, object]],
    ) -> tuple[str, ...]:
        available = self._live_by_name(live)
        ordered: list[str] = []
        for name in (*self._specific_names(requested), *self.base_fallback_order):
            item = available.get(name)
            if item is None or name in ordered or self._blocked(name, item):
                continue
            ordered.append(name)
        return tuple(ordered)

    @staticmethod
    def classify_failure(error: BaseException | str) -> str:
        message = str(error).casefold()
        if any(marker in message for marker in _INCOMPATIBLE_MARKERS):
            return "incompatible"
        if any(marker in message for marker in _CAPABILITY_MARKERS):
            return "capability"
        if any(marker in message for marker in _TRANSIENT_MARKERS):
            return "transient"
        return "unknown"

    def record_success(self, model: str, digest: str, profile: str) -> None:
        self._state[model] = {
            "digest": digest,
            "status": "compatible",
            "profile": str(profile)[:64],
            "error": "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._persist()

    def record_failure(self, model: str, digest: str, error: BaseException | str) -> str:
        classification = self.classify_failure(error)
        status = {
            "incompatible": "quarantined",
            "capability": "capability_limited",
            "transient": "transient_error",
            "unknown": "failed",
        }[classification]
        self._state[model] = {
            "digest": digest,
            "status": status,
            "profile": "",
            "error": f"{type(error).__name__}: {error}"[:1000],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._persist()
        return classification

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        payload = {"schema_version": 1, "models": self._state}
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)

    def inventory(
        self,
        configured: Sequence[str],
        live: Mapping[str, Mapping[str, object]] | Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        available = self._live_by_name(live)
        hidden = {
            alternate
            for rule in self.model_rules.values()
            for alternate in tuple(rule.get("alternates", ()))
        }
        ordered = list(dict.fromkeys(str(name) for name in configured if isinstance(name, str) and name))
        ordered.extend(name for name in available if name not in hidden and name not in ordered)
        configured_set = set(configured)
        result: list[dict[str, object]] = []
        for requested in ordered:
            specific = [name for name in self._specific_names(requested) if name in available]
            unblocked = [name for name in specific if not self._blocked(name, available[name])]
            effective = (unblocked or specific or [None])[0]
            item = available.get(effective) if effective else None
            digest = self.digest(item)
            state = self._matching_state(str(effective), digest) if effective else None
            installed = bool(specific)
            status = state.get("status") if state else ("untested" if installed else "not_installed")
            runnable: bool | None
            if status == "compatible":
                runnable = True
            elif status in _FAILED_STATUSES or not installed:
                runnable = False
            else:
                runnable = None
            details = item.get("details", {}) if isinstance(item, Mapping) else {}
            details = details if isinstance(details, Mapping) else {}
            rule = self.model_rules.get(requested, {})
            fallback_reason = ""
            if effective and effective != requested:
                fallback_reason = str(rule.get("reason", ""))[:1000]
            elif state and state.get("error"):
                fallback_reason = state["error"]
            result.append({
                "name": requested,
                "requested_model": requested,
                "effective_model": effective,
                "configured": requested in configured_set,
                "installed": installed,
                "runnable": runnable,
                "compatibility_status": status,
                "compatibility_profile": state.get("profile") if state else None,
                "fallback_reason": fallback_reason or None,
                "digest": digest or None,
                "size": item.get("size") if isinstance(item, Mapping) else None,
                "quantization": details.get("quantization_level"),
                "context_length": details.get("context_length"),
                "capabilities": list(item.get("capabilities", [])) if isinstance(item, Mapping) else [],
            })
        return result
