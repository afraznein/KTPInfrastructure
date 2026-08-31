#!/usr/bin/env python3
"""Standalone validation suite for the frozen development-candidate packet."""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path


PACKET = Path(__file__).resolve().parents[1]
NEGATIVE_CASE_COUNT = 156
sys.dont_write_bytecode = True
sys.path.insert(0, str(PACKET / "implementation"))

import build_public_report_v1 as public  # noqa: E402
import validate_public_report_v1 as validate  # noqa: E402


def load(relative: str):
    return json.loads((PACKET / relative).read_text(encoding="utf-8"))


def documents_for_match(match_id: str):
    analytics = deepcopy(load("producer-inputs/analytics-v3.synthetic.json"))
    readiness = deepcopy(load("producer-inputs/readiness-v1.synthetic.json"))
    timeline = deepcopy(load("producer-inputs/timeline-v1.synthetic.json"))
    momentum = deepcopy(load("producer-inputs/momentum-v1.synthetic.json"))
    analytics["match_id"] = analytics["match"]["match_id"] = match_id
    readiness["match_id"] = match_id
    timeline["match_id"] = match_id
    momentum["match_id"] = match_id
    return public.build_bundle_documents(
        analytics, readiness, None, timeline, momentum,
        schema_dir=PACKET / "schemas",
    )


class FrozenPacketTests(unittest.TestCase):
    def test_concatenated_sensitive_boundaries_and_ordinary_controls(self):
        for unsafe in (
            "HMACPlayerKeydeadbeef", "AuditIdentitydeadbeef", "Elo1500",
            "Rating1500", "Position12", "Coordinates12", "Route12", "Cell12",
            "Clan-HMACPlayerKeydeadbeef", "Clan-Elo1500", "Map-Rating1500",
            "Map-Position12", "Map-Coordinates12", "Map-Route12", "Map-Cell12",
            "ClanHMACPlayerKeydeadbeef", "ClanElo1500", "MapRating1500",
            "MapPosition12", "MapCoordinates12", "MapRoute12", "MapCell12",
            "DevelopmentElo1500", "GoldenElo1500", "MelodyElo1500",
            "OperatingRating1500", "OppositionPosition12",
            "ClanHMACIdentitydeadbeef", "ClanEloScore1500",
            "MapRatingValue1500", "MapPositionSamples12",
            "MapCoordinateData12", "MapRouteData12", "MapCellKey12",
            "HMACAuditKeydeadbeef", "HMACAuditdeadbeef",
            "HMACAuditIdentitydeadbeef", "HMACAuditPlayerKeydeadbeef",
            "EloRank1500", "EloRanks1500", "EloRanked1500", "EloRanking1500",
            "HMACAuditIDdeadbeef", "EloPlayerRank1500", "EloPlayerRanks1500",
            "EloPlayerRanked1500", "EloPlayerRanking1500",
            "HMACAuditPrivateKeydeadbeef", "HMACAuditDigestdeadbeef",
            "HMACAuditSignaturedeadbeef",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertTrue(public.sensitive_string_reason(unsafe))
                with self.assertRaises(public.PublicContractError):
                    public.safe_display_name(unsafe, label="test")
                analytics = deepcopy(load("producer-inputs/analytics-v3.synthetic.json"))
                analytics["match"]["map_name"] = unsafe
                with self.assertRaises(public.PublicContractError):
                    public.build_public_report(analytics)

        for safe in (
            "dod_anzio", "dod_harrington", "Opposition Blue",
            "Operating Crew", "Melody Makers", "Alpha <script>", "Penelope",
            "Eloise", "Melodic Crew", "Cellophane", "Cellar Door",
            "Celebrating Crew", "Migrating Birds", "Developmental Team", "Router",
        ):
            with self.subTest(safe=safe):
                self.assertIsNone(public.sensitive_string_reason(safe))
                self.assertEqual(public.safe_display_name(safe, label="test"), safe)
                analytics = deepcopy(load("producer-inputs/analytics-v3.synthetic.json"))
                analytics["players"][0]["player_name_at_match"] = safe
                report = public.build_public_report(analytics)
                self.assertEqual(report["players"][0]["name"], safe)

    def test_rebuild_matches_all_goldens(self):
        documents = public.build_bundle_documents(
            load("producer-inputs/analytics-v3.synthetic.json"),
            load("producer-inputs/readiness-v1.synthetic.json"),
            None,
            load("producer-inputs/timeline-v1.synthetic.json"),
            load("producer-inputs/momentum-v1.synthetic.json"),
            schema_dir=PACKET / "schemas",
        )
        for name, document in documents.items():
            self.assertEqual(document, load(f"golden-output/{name}"))

    def test_schema_privacy_semantics_cross_document_and_negative_suite(self):
        result = validate.validate_packet(PACKET)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["positive"]), 3)
        self.assertEqual(result["cross_document"]["status"], "PASS")
        self.assertEqual(len(result["negative"]), NEGATIVE_CASE_COUNT)
        self.assertTrue(all(row["status"] == "PASS" for row in result["negative"]))

    def test_contract_version_is_full_and_consistent(self):
        documents = documents_for_match("packet-contract-TEST")
        self.assertEqual(
            {document["contract_version"] for document in documents.values()},
            {"1.2.0"},
        )

    def test_builder_and_validator_reject_recurrence_resumption_after_null_member(self):
        cases = (
            (("teams", "team_a", "cumulative_timed_points"), "missing_totals"),
            (("momentum",), "missing_momentum"),
            (("momentum_change",), "missing_momentum"),
        )
        for path, reason in cases:
            with self.subTest(path=path):
                source = deepcopy(load("producer-inputs/timeline-v1.synthetic.json"))
                target = source["halves"][0]["bins"][0]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = None
                with self.assertRaisesRegex(public.PublicContractError, "cannot resume"):
                    public.build_public_timeline(source)

                timeline = deepcopy(load("golden-output/public-timeline.json"))
                public_bin = timeline["halves"][0]["bins"][0]
                target = public_bin
                public_path = tuple(
                    "cumulative_points" if key == "cumulative_timed_points" else key
                    for key in path
                )
                for key in public_path[:-1]:
                    target = target[key]
                target[public_path[-1]] = None
                public_bin["coverage"] = {
                    "status": "partial", "reason_code": reason,
                }
                with self.assertRaisesRegex(public.PublicContractError, "cannot resume"):
                    public.validate_public_timeline_semantics(timeline)

    def test_atomic_replacement_never_keeps_stale_files(self):
        documents = {
            name: load(f"golden-output/{name}")
            for name in (
                "public-report.json", "public-timeline.json",
                "momentum-episodes.json",
            )
        }
        target = PACKET / ".packet-test-output"
        self.assertFalse(target.exists(), "stale local packet test output exists")
        try:
            public.publish_bundle_atomic(target, documents, replace=False)
            self.assertEqual({path.name for path in target.iterdir()}, set(documents))
            public.publish_bundle_atomic(target, documents, replace=True)
            self.assertEqual({path.name for path in target.iterdir()}, set(documents))
        finally:
            if target.exists():
                shutil.rmtree(target)

    def test_concurrent_publishers_serialize_without_mixing_or_residue(self):
        first_documents = documents_for_match("packet-concurrent-a-TEST")
        second_documents = documents_for_match("packet-concurrent-b-TEST")
        target = PACKET / ".packet-concurrent-output"
        first_holds_lock = threading.Event()
        release_first = threading.Event()
        errors = []

        def hold_first():
            first_holds_lock.set()
            if not release_first.wait(timeout=5):
                raise RuntimeError("test failed to release first publisher")

        def publish(documents, replace, hook=None):
            try:
                public.publish_bundle_atomic(
                    target, documents, replace=replace, lock_wait_seconds=5,
                    lock_hold_hook=hook,
                )
            except BaseException as exc:  # asserted below
                errors.append(exc)

        first = threading.Thread(
            target=publish, args=(first_documents, False, hold_first)
        )
        second = threading.Thread(
            target=publish, args=(second_documents, True)
        )
        try:
            first.start()
            self.assertTrue(first_holds_lock.wait(timeout=5))
            second.start()
            release_first.set()
            first.join(timeout=10)
            second.join(timeout=10)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            final = {
                path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in target.iterdir()
            }
            self.assertEqual(final, second_documents)
        finally:
            release_first.set()
            first.join(timeout=1)
            second.join(timeout=1)
            if target.exists():
                shutil.rmtree(target)
            for path in PACKET.glob("..packet-concurrent-output.*"):
                if path.is_dir():
                    shutil.rmtree(path)
        self.assertEqual(list(PACKET.glob("..packet-concurrent-output.*")), [])

    def test_stale_lock_recovery_leaves_no_residue(self):
        documents = documents_for_match("packet-stale-lock-TEST")
        target = PACKET / ".packet-stale-output"
        lock = PACKET / "..packet-stale-output.publish.lock"
        lock.mkdir()
        (lock / "owner.json").write_text(
            json.dumps({"owner_token": "crashed"}) + "\n", encoding="utf-8"
        )
        old = time.time() - public.MIN_STALE_LOCK_SECONDS - 10
        os.utime(lock, (old, old))
        try:
            public.publish_bundle_atomic(
                target, documents, replace=False,
                stale_lock_seconds=public.MIN_STALE_LOCK_SECONDS,
                lock_wait_seconds=1,
            )
            self.assertEqual({path.name for path in target.iterdir()}, set(documents))
        finally:
            if target.exists():
                shutil.rmtree(target)
            if lock.exists():
                shutil.rmtree(lock)
            for path in PACKET.glob("..packet-stale-output.stale-lock-*"):
                if path.is_dir():
                    shutil.rmtree(path)
        self.assertEqual(list(PACKET.glob("..packet-stale-output.*")), [])

    def test_crash_between_backup_and_install_restores_old_bundle_and_cleans_residue(self):
        old_documents = documents_for_match("packet-crash-old-TEST")
        next_documents = documents_for_match("packet-crash-next-TEST")
        target = PACKET / ".packet-crash-output"
        backup = PACKET / "..packet-crash-output.old-crashed"
        temporary = PACKET / "..packet-crash-output.tmp-crashed"
        quarantine = PACKET / "..packet-crash-output.stale-lock-orphan"
        lock = PACKET / "..packet-crash-output.publish.lock"
        try:
            public.publish_bundle_atomic(target, old_documents, replace=False)
            target.rename(backup)
            temporary.mkdir()
            for name, document in next_documents.items():
                (temporary / name).write_text(
                    json.dumps(document, indent=2) + "\n", encoding="utf-8"
                )
            quarantine.mkdir()
            lock.mkdir()
            (lock / "owner.json").write_text(
                json.dumps({"owner_token": "crashed"}) + "\n", encoding="utf-8"
            )
            old = time.time() - public.MIN_STALE_LOCK_SECONDS - 10
            os.utime(lock, (old, old))
            with self.assertRaises(FileExistsError):
                public.publish_bundle_atomic(
                    target, next_documents, replace=False,
                    stale_lock_seconds=public.MIN_STALE_LOCK_SECONDS,
                    lock_wait_seconds=1,
                )
            final = {
                path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in target.iterdir()
            }
            self.assertEqual(final, old_documents)
        finally:
            if target.exists():
                shutil.rmtree(target)
            for path in PACKET.glob("..packet-crash-output.*"):
                if path.is_dir():
                    shutil.rmtree(path)
        self.assertEqual(list(PACKET.glob("..packet-crash-output.*")), [])

    def test_nonfinite_stale_threshold_never_steals_live_lock(self):
        documents = documents_for_match("packet-nonfinite-lock-TEST")
        target = PACKET / ".packet-nonfinite-output"
        lock = PACKET / "..packet-nonfinite-output.publish.lock"
        lock.mkdir()
        owner = {"owner_token": "live-owner"}
        owner_file = lock / "owner.json"
        owner_file.write_text(json.dumps(owner) + "\n", encoding="utf-8")
        original_mtime = lock.stat().st_mtime_ns
        try:
            for threshold in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(threshold=threshold):
                    with self.assertRaisesRegex(
                        public.PublicContractError, "finite and at least 300"
                    ):
                        public.publish_bundle_atomic(
                            target, documents, replace=False,
                            stale_lock_seconds=threshold, lock_wait_seconds=0,
                        )
                    self.assertEqual(
                        json.loads(owner_file.read_text(encoding="utf-8")), owner
                    )
                    self.assertEqual(lock.stat().st_mtime_ns, original_mtime)
        finally:
            if target.exists():
                shutil.rmtree(target)
            if lock.exists():
                shutil.rmtree(lock)


if __name__ == "__main__":
    unittest.main(verbosity=2)
