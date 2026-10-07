"""Direct client configuration boundary. Provider management is explicitly capability gated."""
from dataclasses import dataclass, asdict
from typing import Protocol


@dataclass(frozen=True)
class Capabilities:
    verified: bool = False
    remote_revoke: bool = False
    independent_budget: bool = False
    expiry: bool = False
    usage_api: bool = False


class ProviderManagement(Protocol):
    """Implement and verify this contract before enabling any remote-management capability."""
    capabilities: Capabilities

    async def revoke(self, credential_id: str) -> bool: ...
    async def set_budget(self, credential_id: str, amount_fen: int) -> None: ...
    async def usage(self, credential_id: str, start: int, end: int) -> dict: ...


class AnthropicDirectAdapter:
    capabilities = Capabilities()

    def client_env(self, base_url: str, model: str, raw_key: str) -> dict:
        return {'ANTHROPIC_BASE_URL': base_url, 'ANTHROPIC_AUTH_TOKEN': raw_key,
                'ANTHROPIC_MODEL': model, 'ANTHROPIC_DEFAULT_OPUS_MODEL': model,
                'ANTHROPIC_DEFAULT_SONNET_MODEL': model,
                'ANTHROPIC_DEFAULT_HAIKU_MODEL': model.replace('[1m]', ''),
                'CLAUDE_CODE_SUBAGENT_MODEL': model.replace('[1m]', ''),
                'CLAUDE_CODE_EFFORT_LEVEL': 'max'}

    def management_capabilities(self):
        return asdict(self.capabilities)

    @staticmethod
    def probe_result(status: int) -> str:
        return 'revoked' if status == 401 else ('still_valid' if status == 200 else 'uncertain')


class DeepSeekDirectAdapter(AnthropicDirectAdapter):
    capabilities = Capabilities(verified=True)


def get_adapter(kind: str) -> AnthropicDirectAdapter:
    return DeepSeekDirectAdapter() if kind == 'deepseek' else AnthropicDirectAdapter()
