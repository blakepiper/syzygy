"""Pinned data for guided local-model setup (M16.3a, M16.5a).

`catalog.yaml` is the curated model catalog; `runtimes.yaml` is the
allowlist of llama.cpp builds Syzygy will install. Both are loaded and
validated by `syzygy.local_models.catalog`, which refuses anything that is
not HTTPS, digest-pinned, and revision-pinned.
"""
