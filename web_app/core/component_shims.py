from __future__ import annotations

import subprocess
import re
from collections import Counter
from pathlib import Path


class ShimManager:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def refresh(self, components: dict[str, dict[str, tuple[str, ...]]]) -> None:
        for path in self.root.glob("*.cmd"):
            path.unlink()
        counts = Counter(command.casefold() for commands in components.values() for command in commands)
        reserved = {"cmd", "powershell", "pwsh", "python", "node", "git"}
        for component_id, commands in components.items():
            safe_component = component_id.removeprefix("component-")
            for command, argv in commands.items():
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", command):
                    raise ValueError("unsafe component command name")
                body = "@echo off\r\n" + subprocess.list2cmdline(argv) + " %*\r\n"
                target = (self.root / f"borg-{safe_component}-{command}.cmd").resolve()
                target.relative_to(self.root.resolve())
                target.write_text(body, encoding="utf-8")
                if counts[command.casefold()] == 1 and command.casefold() not in reserved:
                    (self.root / f"{command}.cmd").write_text(body, encoding="utf-8")
