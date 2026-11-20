from __future__ import annotations

from uuid import uuid7


class CredentialBroker:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._names: dict[str, str] = {}

    def put(self, name: str, value: str) -> str:
        reference = f"credential:{uuid7()}"
        self._values[reference] = value
        self._names[name] = reference
        return reference

    def reference(self, name: str) -> str:
        return self._names[name]

    def resolve_for_adapter(self, reference: str) -> str:
        return self._values[reference]

    def revoke(self, reference: str) -> None:
        if reference not in self._values:
            raise KeyError(reference)
        del self._values[reference]
        self._names = {name: value for name, value in self._names.items() if value != reference}
