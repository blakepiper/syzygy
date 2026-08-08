"""The local settings document (`AppPaths.settings_path`).

Application *preferences* - which provider to use, whether the theme is
muted - as opposed to application *data*, which lives in SQLite. Nothing
here ever touches the readings database, and no API key is ever written
here (those are in the OS keyring; see
`syzygy.interpretation.providers.api_keys`).

The file is a namespaced JSON object:

```json
{"provider": {"provider_id": "openai", "model_id": "gpt-4o-mini"},
 "audio": {"muted": false}}
```

**Why this module exists.** Until M15, `settings.json` *was* the provider
selection - `save_selection` wrote the whole file with
`model_dump_json()`. Adding any second setting to that file would have
silently destroyed the first one on the next write. `update_document`
read-modify-writes and preserves keys it does not know about, so a
setting added later (M14's `animations = full|reduced|off`, say) cannot
clobber one added earlier, and an older build cannot destroy a newer
build's settings.

Reads never raise. A missing, unreadable, or corrupt settings file means
"no preferences expressed", which every caller already handles - refusing
to start because a preferences file has a stray comma would be absurd.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

#: Top-level keys. One per subsystem that persists a preference.
PROVIDER_SECTION: Final = "provider"
AUDIO_SECTION: Final = "audio"


def load_document(path: Path) -> dict[str, Any]:
    """The whole settings document, or `{}` if there isn't a usable one."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        loaded = json.loads(raw)
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def load_section(path: Path, section: str) -> dict[str, Any]:
    """One section of the document, or `{}`."""
    value = load_document(path).get(section)
    return value if isinstance(value, dict) else {}


def save_document(path: Path, document: Mapping[str, Any]) -> None:
    """Write the whole document. Prefer `save_section` unless you really
    do mean to replace everything."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(document), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def save_section(path: Path, section: str, values: Mapping[str, Any] | None) -> None:
    """Replace `section`, leaving every other section untouched.

    `None` removes the section, which is how a preference is reset to its
    default rather than pinned to it.
    """
    document = load_document(path)
    if values is None:
        document.pop(section, None)
    else:
        document[section] = dict(values)
    save_document(path, document)
