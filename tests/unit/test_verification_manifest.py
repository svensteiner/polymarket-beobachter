from pathlib import Path

import pytest

from analytics.verification_manifest import ManifestError, collect_manifest


def test_manifest_is_sorted_and_scoped(tmp_path):
    (tmp_path / "z.py").write_text("z", encoding="utf-8")
    (tmp_path / "requirements-test.txt").write_text("x", encoding="utf-8")
    (tmp_path / "analytics").mkdir()
    (tmp_path / "analytics" / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "README.md").write_text("ignored", encoding="utf-8")
    manifest = collect_manifest(tmp_path)
    assert list(manifest) == ["analytics/a.py", "requirements-test.txt", "z.py"]
    assert manifest["z.py"]["size"] == 1


def test_manifest_rejects_oversize_and_escape(tmp_path):
    (tmp_path / "large.py").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ManifestError):
        collect_manifest(tmp_path)

    outside = tmp_path.parent / "outside.py"
    outside.write_text("outside", encoding="utf-8")
    try:
        link = tmp_path / "escape.py"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable")
        (tmp_path / "large.py").unlink()
        with pytest.raises(ManifestError):
            collect_manifest(tmp_path)
    finally:
        outside.unlink(missing_ok=True)


def test_manifest_detects_file_mutation_during_hash(tmp_path, monkeypatch):
    source = tmp_path / "source.py"
    source.write_text("before", encoding="utf-8")
    original = Path.open

    def mutate(path, *args, **kwargs):
        if path == source and args == ("rb",):
            source.write_text("after", encoding="utf-8")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", mutate)
    with pytest.raises(ManifestError):
        collect_manifest(tmp_path)


def test_manifest_rejects_internal_alias(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("source", encoding="utf-8")
    alias = tmp_path / "alias.py"
    try:
        alias.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ManifestError, match="alias or symlink"):
        collect_manifest(tmp_path)


def test_manifest_add_delete_cache_and_limits(tmp_path, monkeypatch):
    import analytics.verification_manifest as manifest
    (tmp_path / "analytics" / "__pycache__").mkdir(parents=True)
    (tmp_path / "analytics" / "__pycache__" / "ignored.py").write_text("ignored")
    before = collect_manifest(tmp_path)
    assert before == {}
    source = tmp_path / "new.py"
    source.write_text("new")
    assert collect_manifest(tmp_path) != before
    source.unlink()
    assert collect_manifest(tmp_path) == before
    source.write_text("new")
    monkeypatch.setattr(manifest, "MAX_FILES", 0)
    with pytest.raises(ManifestError, match="file limit"):
        collect_manifest(tmp_path)
    monkeypatch.setattr(manifest, "MAX_FILES", 1000)
    monkeypatch.setattr(manifest, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(ManifestError, match="byte limit"):
        collect_manifest(tmp_path)


def test_manifest_enumeration_error_is_structured(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "iterdir", denied)
    with pytest.raises(ManifestError, match="unavailable"):
        collect_manifest(tmp_path)
