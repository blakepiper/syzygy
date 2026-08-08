"""API key resolution and storage for hosted providers (DESIGN.md §13.3).

Never read from or written to the Syzygy SQLite database. The OS keyring
is the preferred store; a plain environment variable is an acceptable
fallback (for headless use, CI, or a keyring-less system), checked only
if the keyring has nothing for that provider. Keys are never logged or
otherwise surfaced in diagnostics (DESIGN.md §28).
"""

from __future__ import annotations

import os
from typing import Final

import keyring
import keyring.errors

#: Namespaced per provider so clearing one provider's key can never touch
#: another's, and so a `keyring list` in a shared credential manager reads
#: unambiguously.
_KEYRING_SERVICE_PREFIX: Final = "syzygy"
_KEYRING_USERNAME: Final = "api_key"


class MissingAPIKeyError(RuntimeError):
    """No key in the keyring and none in the environment fallback either."""

    def __init__(self, provider_id: str, env_var: str) -> None:
        super().__init__(
            f"No API key found for provider {provider_id!r}. Store one with "
            f"`syzygy model configure {provider_id}`, or set the {env_var} "
            "environment variable."
        )
        self.provider_id = provider_id
        self.env_var = env_var


def _service_name(provider_id: str) -> str:
    return f"{_KEYRING_SERVICE_PREFIX}-{provider_id}"


def resolve_api_key(provider_id: str, env_var: str) -> str:
    """Look up `provider_id`'s API key: keyring first, then `env_var`.

    Raises `MissingAPIKeyError` if neither has one - callers should let
    this propagate rather than silently proceeding unauthenticated.
    """
    stored = keyring.get_password(_service_name(provider_id), _KEYRING_USERNAME)
    if stored:
        return stored
    from_env = os.environ.get(env_var)
    if from_env:
        return from_env
    raise MissingAPIKeyError(provider_id, env_var)


def store_api_key(provider_id: str, api_key: str) -> None:
    keyring.set_password(_service_name(provider_id), _KEYRING_USERNAME, api_key)


def delete_api_key(provider_id: str) -> None:
    """Remove `provider_id`'s stored key. Safe to call if none is stored."""
    try:
        keyring.delete_password(_service_name(provider_id), _KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


def has_stored_api_key(provider_id: str) -> bool:
    return keyring.get_password(_service_name(provider_id), _KEYRING_USERNAME) is not None
