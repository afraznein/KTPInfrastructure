from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import fetch_engine_artifact as fea  # noqa: E402

COMMIT = "c1c028b8671c866f61b3adeabf33266fce022743"
REPO = "afraznein/KTP-ReHLDS"
ELF = fea.ELF32_MAGIC + b"\x00" * 64


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, blob in members.items():
            archive.writestr(name, blob)
    return buffer.getvalue()


class FakeHttp:
    """Replaces the only class in the module that touches the network."""

    def __init__(self, *, commit_status=200, artifacts=None, artifact_status=200,
                 zip_status=200, payload=None):
        self.commit_status = commit_status
        self.artifacts = artifacts if artifacts is not None else [{
            "id": 7, "name": f"rehlds-engine-{COMMIT}", "expired": False,
            "expires_at": "2026-09-23T12:28:48Z", "workflow_run": {"id": 34351065165},
        }]
        self.artifact_status = artifact_status
        self.zip_status = zip_status
        self.payload = payload if payload is not None else _zip(
            {"engine_i486.so": ELF, "HLTV/Proxy/proxy.so": ELF})

    def get_json(self, path):
        if "/commits/" in path:
            return self.commit_status, ({"sha": COMMIT} if self.commit_status == 200 else None)
        return self.artifact_status, ({"artifacts": self.artifacts}
                                      if self.artifact_status == 200 else None)

    def get_bytes(self, path):
        return self.zip_status, (self.payload if self.zip_status == 200 else b"")


def _fetch(http, tmp_path):
    return fea.fetch(http, repo=REPO, ref="main", prefix="rehlds-engine-",
                     member="engine_i486.so", out_dir=tmp_path)


def test_happy_path_writes_the_engine_and_reports_its_identity(tmp_path):
    provenance = _fetch(FakeHttp(), tmp_path)
    engine = tmp_path / "engine_i486.so"
    assert engine.read_bytes() == ELF
    assert provenance["commit"] == COMMIT
    assert provenance["artifact_name"] == f"rehlds-engine-{COMMIT}"
    assert provenance["sha256"] == __import__("hashlib").sha256(ELF).hexdigest()
    assert provenance["bytes"] == len(ELF)


def test_no_artifact_for_that_commit_is_fatal_and_writes_nothing(tmp_path):
    with pytest.raises(fea.Failure) as caught:
        _fetch(FakeHttp(artifacts=[]), tmp_path)
    assert caught.value.code == fea.EXIT_NO_ARTIFACT
    assert not (tmp_path / "engine_i486.so").exists()


def test_expired_artifact_is_its_own_outcome_not_merely_missing(tmp_path):
    expired = [{"id": 7, "name": f"rehlds-engine-{COMMIT}", "expired": True,
                "expires_at": "2026-08-01T00:00:00Z"}]
    with pytest.raises(fea.Failure) as caught:
        _fetch(FakeHttp(artifacts=expired), tmp_path)
    assert caught.value.code == fea.EXIT_EXPIRED
    assert "not byte-reproducible" in caught.value.message


def test_a_live_artifact_beside_an_expired_one_is_still_used(tmp_path):
    mixed = [
        {"id": 1, "name": f"rehlds-engine-{COMMIT}", "expired": True},
        {"id": 9, "name": f"rehlds-engine-{COMMIT}", "expired": False},
    ]
    assert _fetch(FakeHttp(artifacts=mixed), tmp_path)["artifact_id"] == 9


def test_an_artifact_under_another_name_does_not_satisfy_the_request(tmp_path):
    other = [{"id": 7, "name": "rehlds-engine-deadbeef", "expired": False}]
    with pytest.raises(fea.Failure) as caught:
        _fetch(FakeHttp(artifacts=other), tmp_path)
    assert caught.value.code == fea.EXIT_NO_ARTIFACT


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_token_says_which_scope_is_missing(tmp_path, status):
    with pytest.raises(fea.Failure) as caught:
        _fetch(FakeHttp(zip_status=status), tmp_path)
    assert caught.value.code == fea.EXIT_AUTH
    assert "actions:read" in caught.value.message


def test_an_unresolvable_ref_is_distinguished_from_a_missing_artifact(tmp_path):
    with pytest.raises(fea.Failure) as caught:
        _fetch(FakeHttp(commit_status=404), tmp_path)
    assert caught.value.code == fea.EXIT_NO_REF


def test_a_zip_without_the_engine_is_rejected_and_names_what_it_held(tmp_path):
    payload = _zip({"HLTV/Proxy/proxy.so": ELF})
    with pytest.raises(fea.Failure) as caught:
        _fetch(FakeHttp(payload=payload), tmp_path)
    assert caught.value.code == fea.EXIT_PAYLOAD
    assert "HLTV/Proxy/proxy.so" in caught.value.message


def test_a_64_bit_engine_is_refused(tmp_path):
    payload = _zip({"engine_i486.so": b"\x7fELF\x02" + b"\x00" * 64})
    with pytest.raises(fea.Failure) as caught:
        _fetch(FakeHttp(payload=payload), tmp_path)
    assert caught.value.code == fea.EXIT_PAYLOAD


def test_every_failure_path_has_its_own_exit_code():
    codes = {fea.EXIT_NO_REF, fea.EXIT_NO_ARTIFACT, fea.EXIT_EXPIRED,
             fea.EXIT_AUTH, fea.EXIT_PAYLOAD}
    assert len(codes) == 5 and 0 not in codes and 1 not in codes


def test_main_returns_the_failure_code_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(fea, "Http", lambda token, api: FakeHttp(artifacts=[]))
    code = fea.main(["--ref", "main", "--out", str(tmp_path)])
    assert code == fea.EXIT_NO_ARTIFACT


def test_main_writes_provenance_json_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(fea, "Http", lambda token, api: FakeHttp())
    target = tmp_path / "provenance.json"
    assert fea.main(["--ref", "main", "--out", str(tmp_path),
                     "--provenance", str(target)]) == 0
    assert json.loads(target.read_text())["commit"] == COMMIT
