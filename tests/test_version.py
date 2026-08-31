from novariusirc.version import BOT_VERSION, _format_native_version


def test_native_version_includes_valid_embedded_build_information() -> None:
    assert _format_native_version(
        {
            "schema": 1,
            "commit": "38d5e1d0606730258c8ccc6aebd5188d96308f8c",
            "built_at": "2026-08-31T21:04:39Z",
        }
    ) == (
        f"NovariusIRC {BOT_VERSION} "
        "(commit 38d5e1d06067; built 2026-08-31T21:04:39Z)"
    )


def test_native_version_ignores_invalid_build_information() -> None:
    assert _format_native_version(
        {"schema": 1, "commit": "not-a-commit", "built_at": "today"}
    ) == f"NovariusIRC {BOT_VERSION}"
