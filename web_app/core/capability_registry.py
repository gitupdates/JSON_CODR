from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import Field

from web_app.core.adapters import CapabilityCall
from web_app.core.contracts import FrozenContract


class CapabilityDefinition(FrozenContract):
    capability_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    risk: str = Field(min_length=1)
    autonomous: bool


_DEFAULT_DEFINITIONS = (
    CapabilityDefinition(capability_id="project.read", operation="read", risk="low", autonomous=True),
    CapabilityDefinition(capability_id="project.search", operation="search", risk="low", autonomous=True),
    CapabilityDefinition(capability_id="project.discover", operation="discover", risk="low", autonomous=True),
    CapabilityDefinition(capability_id="project.patch", operation="bounded_edit", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="project.test", operation="test", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="inference.generate", operation="generate", risk="low", autonomous=True),
    CapabilityDefinition(capability_id="model.generate", operation="generate", risk="low", autonomous=True),
    CapabilityDefinition(capability_id="native.read", operation="read", risk="low", autonomous=True),
    CapabilityDefinition(capability_id="native.write", operation="bounded_edit", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="native.edit", operation="bounded_edit", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="native.shell", operation="command", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="git.execute", operation="git", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="git.commit", operation="commit", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="git.push", operation="push", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="checkpoint.create", operation="checkpoint", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="checkpoint.restore", operation="destructive", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="terminal.session", operation="session", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="terminal.execute", operation="command", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="terminal.interrupt", operation="interrupt", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="terminal.close", operation="close", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="component.install", operation="install", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="component.execute", operation="execute", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="system.activate", operation="activation", risk="sensitive", autonomous=False),
    CapabilityDefinition(capability_id="system.rollback", operation="rollback", risk="sensitive", autonomous=False),
)


class CapabilityRegistry:
    def __init__(self, definitions: Iterable[CapabilityDefinition] = ()) -> None:
        values = tuple(definitions)
        self._definitions = {definition.capability_id: definition for definition in values}
        if len(self._definitions) != len(values):
            raise ValueError("duplicate capability definition")

    @classmethod
    def default(cls, extra_definitions: Iterable[CapabilityDefinition] = ()) -> "CapabilityRegistry":
        return cls((*_DEFAULT_DEFINITIONS, *extra_definitions))

    def resolve(self, capability_id: str) -> CapabilityDefinition:
        try:
            return self._definitions[capability_id]
        except KeyError as error:
            raise LookupError(f"unknown capability: {capability_id}") from error

    def normalize(self, call: CapabilityCall) -> CapabilityCall:
        definition = self.resolve(call.capability_id)
        if call.operation != definition.operation:
            raise ValueError("capability operation does not match the registered operation")
        return call.model_copy(update={"operation": definition.operation})

    def require_registered(self, adapters: Mapping[str, object]) -> None:
        missing = sorted(set(adapters) - set(self._definitions))
        if missing:
            raise ValueError(f"registered adapters require capability definitions: {', '.join(missing)}")
