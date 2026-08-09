"""The download pipeline, against a fake HTTP server (M16.5e, M16.6f).

No network. Every case is driven through `httpx.MockTransport`, including
the awkward server behaviours that only show up in the field: a range
request answered with a full body, a `Content-Length` that disagrees with
the catalog, a redirect loop, and a byte-perfect file whose digest is
still wrong.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from syzygy.local_models.contracts import FailureKind
from syzygy.local_models.download import (
    DISK_HEADROOM_BYTES,
    DownloadCancelled,
    DownloadError,
    DownloadRequest,
    discard_partial,
    download_verified,
    verify_digest,
)
from syzygy.local_models.paths import read_ownership
from syzygy.local_models.runtime_state import load_runtime_state

#: Deliberately larger than `download.CHUNK_BYTES`, so the streaming loop
#: really iterates and cancellation has somewhere to land.
PAYLOAD = b"syzygy-test-payload-padding-0123" * (3 * 1024 * 1024 // 32)
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
URL = "https://huggingface.co/test/test/resolve/" + "0" * 40 + "/test.gguf"


def request_for(paths, *, sha256: str = DIGEST, size: int = len(PAYLOAD)) -> DownloadRequest:
    return DownloadRequest(
        key="test-artifact",
        url=URL,
        sha256=sha256,
        expected_bytes=size,
        destination=paths.models_dir / "test.gguf",
    )


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def whole_file(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        content=PAYLOAD,
        headers={"Content-Length": str(len(PAYLOAD)), "ETag": '"v1"'},
    )


def ranged(request: httpx.Request) -> httpx.Response:
    """A well-behaved server that honours `Range`."""
    header = request.headers.get("Range")
    if header is None:
        return whole_file(request)
    start = int(header.split("=", 1)[1].split("-", 1)[0])
    body = PAYLOAD[start:]
    return httpx.Response(
        206,
        content=body,
        headers={
            "Content-Length": str(len(body)),
            "Content-Range": f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}",
            "ETag": '"v1"',
        },
    )


# -- the happy path ----------------------------------------------------------


def test_a_verified_download_is_promoted_and_marked_as_owned(local_paths) -> None:
    seen: list[tuple[int, int | None]] = []
    path = download_verified(
        request_for(local_paths),
        local_paths,
        on_progress=lambda done, total: seen.append((done, total)),
        client=client_for(whole_file),
    )

    assert path.read_bytes() == PAYLOAD
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    marker = read_ownership(local_paths.models_dir)
    assert marker is not None and "test.gguf" in marker.entries
    # The partial is gone, and so is its resume record.
    assert not list(local_paths.partial_dir.glob("*.partial"))
    assert load_runtime_state(local_paths.state_path).download("test-artifact") is None


def test_an_already_correct_file_is_not_downloaded_again(local_paths) -> None:
    destination = local_paths.models_dir / "test.gguf"
    destination.write_bytes(PAYLOAD)

    def refuse(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should have been made")

    path = download_verified(
        request_for(local_paths), local_paths, client=client_for(refuse)
    )
    assert path == destination


def test_nothing_is_ever_written_to_the_destination_before_verification(local_paths) -> None:
    def truncated(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PAYLOAD[:100], headers={"ETag": '"v1"'})

    with pytest.raises(DownloadError) as caught:
        download_verified(request_for(local_paths), local_paths, client=client_for(truncated))

    assert caught.value.failure.kind is FailureKind.UPSTREAM_CHANGED
    assert not (local_paths.models_dir / "test.gguf").exists()


# -- resume ------------------------------------------------------------------


def test_an_interrupted_download_resumes_from_the_partial(local_paths) -> None:
    calls: list[str | None] = []

    def counting(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("Range"))
        return ranged(request)

    chunks_seen = 0

    def cancel_after_one_chunk() -> bool:
        nonlocal chunks_seen
        chunks_seen += 1
        return chunks_seen > 1

    with pytest.raises(DownloadCancelled):
        download_verified(
            request_for(local_paths),
            local_paths,
            cancel=cancel_after_one_chunk,
            client=client_for(counting),
        )

    partial = local_paths.partial_dir / "test-artifact.partial"
    assert partial.exists()
    record = load_runtime_state(local_paths.state_path).download("test-artifact")
    assert record is not None and record.downloaded_bytes > 0

    path = download_verified(request_for(local_paths), local_paths, client=client_for(counting))

    assert path.read_bytes() == PAYLOAD
    assert calls[-1] is not None and calls[-1].startswith("bytes=")


def test_a_server_that_ignores_ranges_restarts_cleanly(local_paths) -> None:
    partial = local_paths.partial_dir / "test-artifact.partial"
    partial.write_bytes(PAYLOAD[:100])
    from syzygy.local_models.runtime_state import (
        DownloadProgress,
        save_runtime_state,
    )
    from syzygy.local_models.runtime_state import (
        load_runtime_state as load,
    )

    save_runtime_state(
        local_paths.state_path,
        load(local_paths.state_path).with_download(
            DownloadProgress(
                key="test-artifact",
                url=URL,
                partial_path=str(partial),
                downloaded_bytes=100,
                etag='"v1"',
            )
        ),
    )

    # `whole_file` answers 200 no matter what Range was asked for.
    path = download_verified(
        request_for(local_paths), local_paths, client=client_for(whole_file)
    )

    # Had the prefix been kept, the file would be 100 bytes too long and
    # the digest would fail. Restarting is the only correct response.
    assert path.read_bytes() == PAYLOAD


def test_a_partial_longer_than_the_finished_file_is_discarded(local_paths) -> None:
    partial = local_paths.partial_dir / "test-artifact.partial"
    partial.write_bytes(PAYLOAD + b"extra")
    from syzygy.local_models.runtime_state import (
        DownloadProgress,
        save_runtime_state,
    )
    from syzygy.local_models.runtime_state import (
        load_runtime_state as load,
    )

    save_runtime_state(
        local_paths.state_path,
        load(local_paths.state_path).with_download(
            DownloadProgress(key="test-artifact", url=URL, partial_path=str(partial))
        ),
    )

    path = download_verified(request_for(local_paths), local_paths, client=client_for(ranged))
    assert path.read_bytes() == PAYLOAD


def test_discarding_a_partial_removes_both_file_and_record(local_paths) -> None:
    partial = local_paths.partial_dir / "test-artifact.partial"
    partial.write_bytes(b"junk")

    discard_partial(local_paths, "test-artifact")

    assert not partial.exists()
    assert load_runtime_state(local_paths.state_path).download("test-artifact") is None


# -- integrity ---------------------------------------------------------------


def test_a_digest_mismatch_discards_the_bytes_rather_than_keeping_them(local_paths) -> None:
    with pytest.raises(DownloadError) as caught:
        download_verified(
            request_for(local_paths, sha256="b" * 64),
            local_paths,
            client=client_for(whole_file),
        )

    assert caught.value.failure.kind is FailureKind.DIGEST_MISMATCH
    assert not (local_paths.models_dir / "test.gguf").exists()
    # Crucially: the partial is gone too, so a later "resume" cannot build
    # on bytes already known to be wrong.
    assert not (local_paths.partial_dir / "test-artifact.partial").exists()


def test_a_declared_length_that_disagrees_with_the_catalog_is_refused(local_paths) -> None:
    def wrong_length(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=PAYLOAD, headers={"Content-Length": str(len(PAYLOAD))}
        )

    with pytest.raises(DownloadError) as caught:
        download_verified(
            request_for(local_paths, size=len(PAYLOAD) + 1),
            local_paths,
            client=client_for(wrong_length),
        )

    assert caught.value.failure.kind is FailureKind.UPSTREAM_CHANGED
    assert caught.value.failure.retryable is False


def test_verify_digest_reports_a_mismatch_without_raising(tmp_path) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(PAYLOAD)

    assert verify_digest(target, DIGEST) is True
    assert verify_digest(target, "c" * 64) is False
    assert verify_digest(tmp_path / "missing", DIGEST) is False


# -- HTTP failure modes ------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, FailureKind.AUTHENTICATION_REQUIRED),
        (403, FailureKind.AUTHENTICATION_REQUIRED),
        (404, FailureKind.UPSTREAM_CHANGED),
        (410, FailureKind.UPSTREAM_CHANGED),
        (416, FailureKind.CORRUPT_PARTIAL),
        (503, FailureKind.OFFLINE),
    ],
)
def test_each_http_status_gets_its_own_recovery(local_paths, status, kind) -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b"nope")

    with pytest.raises(DownloadError) as caught:
        download_verified(request_for(local_paths), local_paths, client=client_for(failing))

    assert caught.value.failure.kind is kind
    assert caught.value.failure.actions


def test_being_offline_is_reported_as_offline(local_paths) -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(DownloadError) as caught:
        download_verified(request_for(local_paths), local_paths, client=client_for(refused))

    assert caught.value.failure.kind is FailureKind.OFFLINE


def test_redirects_are_bounded(local_paths) -> None:
    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": str(request.url)})

    client = httpx.Client(
        transport=httpx.MockTransport(loop), follow_redirects=True, max_redirects=2
    )
    with pytest.raises(DownloadError) as caught:
        download_verified(request_for(local_paths), local_paths, client=client)

    assert caught.value.failure.kind is FailureKind.OFFLINE


# -- disk --------------------------------------------------------------------


def test_insufficient_disk_stops_before_a_single_byte_is_fetched(local_paths, monkeypatch) -> None:
    monkeypatch.setattr(
        "syzygy.local_models.download.free_disk_bytes", lambda _path: DISK_HEADROOM_BYTES
    )

    def refuse(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should have been made")

    with pytest.raises(DownloadError) as caught:
        download_verified(request_for(local_paths), local_paths, client=client_for(refuse))

    assert caught.value.failure.kind is FailureKind.INSUFFICIENT_DISK
    assert caught.value.failure.retryable is False
