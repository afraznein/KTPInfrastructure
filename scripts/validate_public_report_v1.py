#!/usr/bin/env python3
"""Validate schemas, semantics, privacy, and cross-document invariants."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts import build_public_report_v1 as public  # type: ignore  # noqa: E402
except (ModuleNotFoundError, ImportError):  # Frozen packet keeps both modules side by side.
    module_path = Path(__file__).with_name("build_public_report_v1.py")
    spec = importlib.util.spec_from_file_location("packet_public_builder", module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - corrupt packet
        raise RuntimeError(f"cannot load packet public builder: {module_path}")
    public = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(public)


DOCUMENTS = {
    "public-report.json": "public-report-v1.schema.json",
    "public-timeline.json": "public-timeline-v1.schema.json",
    "momentum-episodes.json": "momentumEpisode-v1.schema.json",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validator_for(schema_path: Path):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "JSON Schema validation requires jsonschema>=4.18."
        ) from exc
    schema = read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def set_path(document: Any, expression: str, value: Any) -> None:
    """Set a simple dot/list path used by the negative fixture format."""
    import re

    tokens: list[str | int] = []
    for name, index in re.findall(r"(?:^|\.)([^.\[]+)|\[([0-9]+)\]", expression):
        tokens.append(name if name else int(index))
    target = document
    for token in tokens[:-1]:
        target = target[token]
    target[tokens[-1]] = value


def _semantic_validate(document_name: str, document: Mapping[str, Any]) -> None:
    if document_name == "public-report.json":
        public.validate_public_report_semantics(document)
    elif document_name == "public-timeline.json":
        public.validate_public_timeline_semantics(document)
    elif document_name == "momentum-episodes.json":
        public.validate_momentum_semantics(document)
    else:  # pragma: no cover - fixed internal mapping
        raise ValueError(document_name)


def _negative_cases(negative_root: Path) -> list[dict[str, Any]]:
    expected = read_json(negative_root / "expected-rejections.json")
    cases: list[dict[str, Any]] = []
    for fixture_name in expected["fixtures"]:
        fixture = read_json(negative_root / fixture_name)
        if "cases" in fixture:
            cases.extend(fixture["cases"])
        else:
            cases.append(fixture)
    expected_count = expected.get("case_count")
    if expected_count != len(cases):
        raise ValueError(
            "negative fixture inventory mismatch: "
            f"expected {expected_count!r}, loaded {len(cases)}"
        )
    names = [case.get("name") for case in cases]
    if len(names) != len(set(names)):
        raise ValueError("negative fixture case names must be unique")
    return cases


def validate_packet(packet_root: Path) -> dict[str, Any]:
    schema_root = packet_root / "schemas"
    golden_root = packet_root / "fixtures" / "golden"
    if not golden_root.is_dir():
        golden_root = packet_root / "golden-output"
    negative_root = packet_root / "fixtures" / "privacy-negative"
    if not negative_root.is_dir():
        negative_root = packet_root / "privacy-negative-fixtures"
    result: dict[str, Any] = {
        "schema_version": 2,
        "contract_version": public.CONTRACT_VERSION,
        "status": "PASS",
        "positive": [],
        "cross_document": {"status": "PASS", "errors": []},
        "negative": [],
    }

    validators = {}
    golden = {}
    for document_name, schema_name in DOCUMENTS.items():
        validator = validator_for(schema_root / schema_name)
        document = read_json(golden_root / document_name)
        schema_errors = sorted(
            validator.iter_errors(document), key=lambda item: list(item.path)
        )
        privacy_errors = public.privacy_violations(document)
        semantic_errors = []
        try:
            _semantic_validate(document_name, document)
        except (ValueError, KeyError, TypeError) as exc:
            semantic_errors.append(str(exc))
        errors = [error.message for error in schema_errors] + privacy_errors + semantic_errors
        if errors:
            result["status"] = "FAIL"
        result["positive"].append({
            "document": document_name,
            "status": "PASS" if not errors else "FAIL",
            "errors": errors,
        })
        validators[document_name] = validator
        golden[document_name] = document

    try:
        public.validate_bundle_consistency(
            golden["public-report.json"], golden["public-timeline.json"],
            golden["momentum-episodes.json"],
        )
    except (ValueError, KeyError, TypeError) as exc:
        result["status"] = "FAIL"
        result["cross_document"] = {"status": "FAIL", "errors": [str(exc)]}

    for fixture in _negative_cases(negative_root):
        document_name = fixture["document"]
        mutated = copy.deepcopy(golden[document_name])
        set_path(mutated, fixture["inject_path"], fixture["inject_value"])
        privacy_rejected = bool(public.privacy_violations(mutated))
        schema_rejected = bool(list(validators[document_name].iter_errors(mutated)))
        semantic_rejected = False
        try:
            _semantic_validate(document_name, mutated)
            bundle = dict(golden)
            bundle[document_name] = mutated
            public.validate_bundle_consistency(
                bundle["public-report.json"], bundle["public-timeline.json"],
                bundle["momentum-episodes.json"],
            )
        except (ValueError, KeyError, TypeError):
            semantic_rejected = True
        observed = {
            "privacy": privacy_rejected,
            "schema": schema_rejected,
            "semantic": semantic_rejected,
        }
        expected_guards = set(fixture["expected_guards"])
        passed = all(observed[guard] for guard in expected_guards)
        if not passed:
            result["status"] = "FAIL"
        result["negative"].append({
            "case": fixture["name"],
            "status": "PASS" if passed else "FAIL",
            "expected_guards": sorted(expected_guards),
            "observed": observed,
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_packet(args.packet_root)
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
