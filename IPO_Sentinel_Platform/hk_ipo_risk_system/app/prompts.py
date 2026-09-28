from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import yaml

from .config import PROJECT_ROOT


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    label: str
    temperature: float
    tools: tuple[str, ...]
    depends_on: tuple[str, ...]
    mode: str | None
    system_prompt: str
    user_template: str


class PromptRegistry:
    def __init__(self, prompt_path: Path | None = None, agent_path: Path | None = None):
        self.prompt_path = prompt_path or PROJECT_ROOT / "prompts" / "prompt_pack.md"
        self.agent_path = agent_path or PROJECT_ROOT / "config" / "agents.yaml"
        self.version = "unknown"
        self.global_system_prompt = ""
        self._definitions: dict[str, PromptDefinition] = {}
        self.reload()

    @staticmethod
    def _code_block(section: str, heading: str, language: str) -> str:
        pattern = rf"#### {re.escape(heading)}\s+```{language}\s+(.*?)\s+```"
        match = re.search(pattern, section, flags=re.DOTALL)
        return match.group(1).strip() if match else ""

    def reload(self) -> None:
        markdown = self.prompt_path.read_text(encoding="utf-8")
        config = yaml.safe_load(self.agent_path.read_text(encoding="utf-8"))
        self.version = str(config["version"])
        global_section = re.search(
            r"## 4\. GLOBAL_SYSTEM_PROMPT.*?```text\s+(.*?)\s+```",
            markdown,
            flags=re.DOTALL,
        )
        self.global_system_prompt = global_section.group(1).strip() if global_section else ""
        safety = re.search(
            r"## 8\. 提示词安全与抗注入条款.*?```text\s+(.*?)\s+```",
            markdown,
            flags=re.DOTALL,
        )
        safety_prompt = safety.group(1).strip() if safety else ""

        sections = re.finditer(
            r"### 5\.\d+ .*?（([A-Z_]+)）(.*?)(?=\n### 5\.\d+|\n## 6\.)",
            markdown,
            flags=re.DOTALL,
        )
        definitions: dict[str, PromptDefinition] = {}
        for match in sections:
            name, section = match.group(1), match.group(2)
            metadata = config["agents"][name]
            role_prompt = self._code_block(section, "ROLE_SYSTEM_PROMPT", "text")
            if name in {
                "DOCUMENT_PARSER_AGENT",
                "RISK_EXTRACTION_AGENT",
                "LEGAL_COMPLIANCE_AGENT",
                "INDUSTRY_PIPELINE_AGENT",
                "MARKET_SENTIMENT_AGENT",
            }:
                role_prompt = f"{role_prompt}\n\n{safety_prompt}".strip()
            definitions[name] = PromptDefinition(
                name=name,
                label=str(metadata["label"]),
                temperature=float(metadata["temperature"]),
                tools=tuple(metadata.get("tools", [])),
                depends_on=tuple(metadata.get("depends_on", [])),
                mode=metadata.get("mode"),
                system_prompt=role_prompt,
                user_template=self._code_block(section, "ROLE_USER_TEMPLATE", "yaml"),
            )
        missing = set(config["agents"]) - set(definitions)
        if missing:
            raise RuntimeError(f"prompt definitions missing: {sorted(missing)}")
        self._definitions = definitions

    def get(self, name: str) -> PromptDefinition:
        return self._definitions[name]

    def public_registry(self) -> list[dict]:
        return [
            {
                "name": item.name,
                "label": item.label,
                "temperature": item.temperature,
                "tools": list(item.tools),
                "depends_on": list(item.depends_on),
                "mode": item.mode,
            }
            for item in self._definitions.values()
        ]

