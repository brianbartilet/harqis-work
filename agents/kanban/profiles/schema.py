"""
Agent profile schema — loaded from YAML files.

Each profile fully describes one logical agent:
  identity, model config, repo context, tools, permissions, hardware, lifecycle.

Profiles support inheritance via `extends: <base-profile-id>`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


# ── Sub-configs ───────────────────────────────────────────────────────────────

@dataclass
class ModelConfig:
    provider: str = "anthropic"
    model_id: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
    system_prompt: str = ""
    system_prompt_file: str = ""

    def resolved_system_prompt(self, base_dir: Optional[Path] = None) -> str:
        if self.system_prompt:
            return self.system_prompt
        if self.system_prompt_file:
            p = Path(self.system_prompt_file)
            if base_dir and not p.is_absolute():
                p = base_dir / p
            return p.read_text(encoding="utf-8")
        return ""


@dataclass
class RepoConfig:
    url: str = ""
    local_path: str = ""
    branch_policy: str = "any"  # any | read-only | feature-branch-only


@dataclass
class ContextConfig:
    repos: list[RepoConfig] = field(default_factory=list)
    working_directory: str = ""
    env_files: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)


@dataclass
class SecretsConfig:
    required: list[str] = field(default_factory=list)
    """Env-var names this agent needs. SecretStore injects only these."""


@dataclass
class ToolsConfig:
    allowed: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    mcp_apps: list[str] = field(default_factory=list)


@dataclass
class FilesystemPermission:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class NetworkPermission:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class GitPermission:
    can_push: bool = False
    protected_branches: list[str] = field(
        default_factory=lambda: ["main", "master", "prod"]
    )
    require_pr: bool = True
    author_name: str = "claude[bot]"
    author_email: str = "claude[bot]@users.noreply.github.com"


@dataclass
class PermissionsConfig:
    filesystem: FilesystemPermission = field(default_factory=FilesystemPermission)
    network: NetworkPermission = field(default_factory=NetworkPermission)
    git: GitPermission = field(default_factory=GitPermission)


@dataclass
class HardwareConfig:
    node_affinity: str = "any"
    fallback_nodes: list[str] = field(default_factory=list)
    requires_display: bool = False
    requires_usb: bool = False
    min_ram_gb: int = 2
    queue: str = "default"


@dataclass
class PersonaConfig:
    """Display identity used to sign comments (Mode B) and to label the agent in audit logs.

    All fields optional. When `display_name` is empty the agent uses its profile id.
    `member_id` is the Trello member ID (24-char hex) — only set after the bot account
    has been created and invited to the board (Mode A).
    """
    display_name: str = ""
    email: str = ""
    avatar_url: str = ""
    signature: str = ""
    role: str = ""
    member_id: str = ""


@dataclass
class ProviderCredentialsConfig:
    """Per-profile Kanban provider credentials (Mode A).

    Each field names the *env var* to read at runtime — the orchestrator looks
    them up and, when present, builds a per-profile `KanbanProvider` so this
    agent's actions are attributed to its own Trello/Jira account.

    When all referenced env vars are unset, the orchestrator falls back to the
    global provider (Mode B — signed comments under the shared bot account).
    """
    trello_api_key_env: str = ""
    trello_api_token_env: str = ""
    jira_email_env: str = ""
    jira_api_token_env: str = ""

    def is_set(self) -> bool:
        """True if at least one credential env var name is configured."""
        return any([
            self.trello_api_key_env,
            self.trello_api_token_env,
            self.jira_email_env,
            self.jira_api_token_env,
        ])


@dataclass
class LifecycleConfig:
    timeout_minutes: int = 20
    on_timeout: str = "move_to_failed"
    on_error: str = "post_error_comment_and_fail"
    on_success: str = "move_to_review"
    auto_approve: bool = False
    max_retries: int = 1
    retry_delay_seconds: int = 30
    detect_dependencies: bool = True
    block_on_missing_secrets: bool = True
    blocked_poll_interval_seconds: int = 300


# ── Root profile ──────────────────────────────────────────────────────────────

@dataclass
class AgentProfile:
    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    extends: str = ""
    model: ModelConfig = field(default_factory=ModelConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    permissions: PermissionsConfig = field(default_factory=PermissionsConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    lifecycle: LifecycleConfig = field(default_factory=LifecycleConfig)
    secrets: SecretsConfig = field(default_factory=SecretsConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    provider_credentials: ProviderCredentialsConfig = field(default_factory=ProviderCredentialsConfig)

    # ── Label matching ────────────────────────────────────────────────────────

    def matches_label(self, label: str) -> bool:
        """Return True if this profile's id matches the given card label."""
        return self.id == label or self.id.startswith(label)

    # ── YAML loading ──────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentProfile:
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            description=data.get("description", ""),
            version=str(data.get("version", "1.0")),
            extends=data.get("extends", ""),
            model=_load_model(data.get("model", {})),
            context=_load_context(data.get("context", {})),
            tools=_load_tools(data.get("tools", {})),
            permissions=_load_permissions(data.get("permissions", {})),
            hardware=_load_hardware(data.get("hardware", {})),
            lifecycle=_load_lifecycle(data.get("lifecycle", {})),
            secrets=_load_secrets(data.get("secrets", {})),
            persona=_load_persona(data.get("persona", {})),
            provider_credentials=_load_provider_credentials(data.get("provider_credentials", {})),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> AgentProfile:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    def merge_base(self, base: AgentProfile) -> AgentProfile:
        """Return a new profile with base values filled in where this profile has defaults."""
        def _pick(mine, base_val):
            return mine if mine != base_val.__class__() else base_val

        return AgentProfile(
            id=self.id,
            name=self.name,
            description=self.description or base.description,
            version=self.version,
            extends=self.extends,
            model=self.model if self.model != ModelConfig() else base.model,
            context=self.context if self.context != ContextConfig() else base.context,
            tools=_merge_tools(self.tools, base.tools),
            permissions=_merge_permissions(self.permissions, base.permissions),
            hardware=self.hardware if self.hardware != HardwareConfig() else base.hardware,
            lifecycle=self.lifecycle if self.lifecycle != LifecycleConfig() else base.lifecycle,
            secrets=_merge_secrets(self.secrets, base.secrets),
            persona=self.persona if self.persona != PersonaConfig() else base.persona,
            provider_credentials=(
                self.provider_credentials
                if self.provider_credentials != ProviderCredentialsConfig()
                else base.provider_credentials
            ),
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_model(d: dict) -> ModelConfig:
    return ModelConfig(
        provider=d.get("provider", "anthropic"),
        model_id=d.get("model_id", "claude-sonnet-4-6"),
        max_tokens=int(d.get("max_tokens", 4096)),
        system_prompt=d.get("system_prompt", ""),
        system_prompt_file=d.get("system_prompt_file", ""),
    )


def _load_context(d: dict) -> ContextConfig:
    repos = [
        RepoConfig(
            url=r.get("url", ""),
            local_path=r.get("local_path", ""),
            branch_policy=r.get("branch_policy", "any"),
        )
        for r in d.get("repos", [])
    ]
    return ContextConfig(
        repos=repos,
        working_directory=d.get("working_directory", ""),
        env_files=d.get("env_files", []),
        config_files=d.get("config_files", []),
    )


def _load_tools(d: dict) -> ToolsConfig:
    return ToolsConfig(
        allowed=d.get("allowed", []),
        denied=d.get("denied", []),
        mcp_servers=d.get("mcp_servers", []),
        mcp_apps=d.get("mcp_apps", []),
    )


def _load_permissions(d: dict) -> PermissionsConfig:
    fs = d.get("filesystem", {})
    net = d.get("network", {})
    git = d.get("git", {})
    return PermissionsConfig(
        filesystem=FilesystemPermission(
            allow=fs.get("allow", []),
            deny=fs.get("deny", []),
        ),
        network=NetworkPermission(
            allow=net.get("allow", []),
            deny=net.get("deny", []),
        ),
        git=GitPermission(
            can_push=git.get("can_push", False),
            protected_branches=git.get(
                "protected_branches", ["main", "master", "prod"]
            ),
            require_pr=git.get("require_pr", True),
            author_name=git.get("author_name", "claude[bot]"),
            author_email=git.get("author_email", "claude[bot]@users.noreply.github.com"),
        ),
    )


def _load_hardware(d: dict) -> HardwareConfig:
    return HardwareConfig(
        node_affinity=d.get("node_affinity", "any"),
        fallback_nodes=d.get("fallback_nodes", []),
        requires_display=d.get("requires_display", False),
        requires_usb=d.get("requires_usb", False),
        min_ram_gb=int(d.get("min_ram_gb", 2)),
        queue=d.get("queue", "default"),
    )


def _load_lifecycle(d: dict) -> LifecycleConfig:
    return LifecycleConfig(
        timeout_minutes=int(d.get("timeout_minutes", 20)),
        on_timeout=d.get("on_timeout", "move_to_failed"),
        on_error=d.get("on_error", "post_error_comment_and_fail"),
        on_success=d.get("on_success", "move_to_review"),
        auto_approve=bool(d.get("auto_approve", False)),
        max_retries=int(d.get("max_retries", 1)),
        retry_delay_seconds=int(d.get("retry_delay_seconds", 30)),
        detect_dependencies=bool(d.get("detect_dependencies", True)),
        block_on_missing_secrets=bool(d.get("block_on_missing_secrets", True)),
        blocked_poll_interval_seconds=int(d.get("blocked_poll_interval_seconds", 300)),
    )


def _load_secrets(d: dict) -> SecretsConfig:
    return SecretsConfig(
        required=d.get("required", []),
    )


def _load_persona(d: dict) -> PersonaConfig:
    return PersonaConfig(
        display_name=d.get("display_name", ""),
        email=d.get("email", ""),
        avatar_url=d.get("avatar_url", ""),
        signature=d.get("signature", ""),
        role=d.get("role", ""),
        member_id=d.get("member_id", ""),
    )


def _load_provider_credentials(d: dict) -> ProviderCredentialsConfig:
    return ProviderCredentialsConfig(
        trello_api_key_env=d.get("trello_api_key_env", ""),
        trello_api_token_env=d.get("trello_api_token_env", ""),
        jira_email_env=d.get("jira_email_env", ""),
        jira_api_token_env=d.get("jira_api_token_env", ""),
    )


def _merge_secrets(mine: SecretsConfig, base: SecretsConfig) -> SecretsConfig:
    # Union of required vars — child + base, deduplicated
    combined = list(dict.fromkeys(mine.required + base.required))
    return SecretsConfig(required=combined)


def _merge_tools(mine: ToolsConfig, base: ToolsConfig) -> ToolsConfig:
    return ToolsConfig(
        allowed=mine.allowed or base.allowed,
        denied=list(set(mine.denied + base.denied)),
        mcp_servers=mine.mcp_servers or base.mcp_servers,
        mcp_apps=mine.mcp_apps or base.mcp_apps,
    )


def _merge_permissions(mine: PermissionsConfig, base: PermissionsConfig) -> PermissionsConfig:
    return PermissionsConfig(
        filesystem=FilesystemPermission(
            allow=mine.filesystem.allow or base.filesystem.allow,
            deny=list(set(mine.filesystem.deny + base.filesystem.deny)),
        ),
        network=NetworkPermission(
            allow=mine.network.allow or base.network.allow,
            deny=list(set(mine.network.deny + base.network.deny)),
        ),
        git=mine.git if mine.git != GitPermission() else base.git,
    )
