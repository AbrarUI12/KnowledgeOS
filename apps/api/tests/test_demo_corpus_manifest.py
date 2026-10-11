"""Validate the demo corpus manifest (Task T4.5).

Tests that the manifest.json produced by `make demo-corpus` is well-formed
and covers all required formats, orgs, and special cases.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

MANIFEST_PATH = (
    Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "corpus" / "demo" / "manifest.json"
)


@pytest.mark.unit
class TestDemoCorpusManifest:
    """Validate the generated manifest.json."""

    @classmethod
    @pytest.fixture(scope="class")
    def manifest(cls) -> list[dict[str, str]]:
        if not MANIFEST_PATH.exists():
            pytest.skip("manifest.json not found; run `make demo-corpus` first")
        data: list[dict[str, str]] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return data

    def test_manifest_not_empty(self, manifest: list[dict[str, str]]) -> None:
        assert len(manifest) > 0, "manifest should contain at least one entry"

    def test_manifest_required_fields(self, manifest: list[dict[str, str]]) -> None:
        required = {"key", "title", "org", "kb", "classification", "acl", "format", "file"}
        for entry in manifest:
            missing = required - set(entry.keys())
            assert not missing, f"entry {entry.get('key', '?')} missing fields: {missing}"

    def test_manifest_unique_keys(self, manifest: list[dict[str, str]]) -> None:
        keys = [e["key"] for e in manifest]
        assert len(keys) == len(set(keys)), "manifest keys must be unique"

    def test_manifest_unique_files(self, manifest: list[dict[str, str]]) -> None:
        files = [e["file"] for e in manifest]
        assert len(files) == len(set(files)), "manifest files must be unique"

    def test_all_formats_represented(self, manifest: list[dict[str, str]]) -> None:
        """Every format in plan §5.3 must be represented."""
        formats = {e["format"] for e in manifest}
        required_formats = {"pdf", "docx", "xlsx", "pptx", "csv", "html", "markdown", "txt"}
        missing = required_formats - formats
        assert not missing, f"missing formats in manifest: {missing}"

    def test_both_orgs_present(self, manifest: list[dict[str, str]]) -> None:
        orgs = {e["org"] for e in manifest}
        assert "acme" in orgs, "Acme org documents missing"
        assert "globex" in orgs, "Globex org documents missing"

    def test_restricted_document_exists(self, manifest: list[dict[str, str]]) -> None:
        """HR compensation doc must be confidential and group-restricted."""
        restricted = [
            e
            for e in manifest
            if e["classification"] == "confidential" and e["acl"].startswith("group:")
        ]
        assert len(restricted) > 0, "no group-restricted confidential document found"

    def test_poisoned_document_exists(self, manifest: list[dict[str, str]]) -> None:
        """The poisoned doc for security testing should be present."""
        # The poisoned doc is identified by its content containing injection text
        # We check it exists in the manifest by key
        keys = {e["key"] for e in manifest}
        assert "acme-eng-notes" in keys, "poisoned document not in manifest"

    def test_manifest_files_exist_on_disk(self, manifest: list[dict[str, str]]) -> None:
        base = MANIFEST_PATH.parent
        for entry in manifest:
            file_path = base / entry["file"]
            assert file_path.exists(), f"file {entry['file']} listed in manifest but not on disk"

    def test_spanish_document_exists(self, manifest: list[dict[str, str]]) -> None:
        keys = {e["key"] for e in manifest}
        assert "acme-hr-politica-vacaciones" in keys, "Spanish policy document missing"
