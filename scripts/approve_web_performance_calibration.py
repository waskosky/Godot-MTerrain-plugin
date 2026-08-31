#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import verify_web_release_gate as release_gate
from web_evidence_common import (
    load_object,
    sha256,
    threshold_contract_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUDGETS = ROOT / "tools" / "web_performance_budgets.json"
DEFAULT_GATE = ROOT / "tools" / "web_release_gate.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", required=True, type=Path)
    parser.add_argument(
        "--evidence",
        required=True,
        action="append",
        type=Path,
        help="Passing normalized performance evidence; repeat for every approved lane",
    )
    parser.add_argument("--operator", required=True)
    parser.add_argument("--budgets", type=Path, default=DEFAULT_BUDGETS)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / "build"
            / "evidence"
            / "web-performance-calibration-approved.json"
        ),
    )
    return parser.parse_args()


def bounded_text(value: str, label: str, maximum: int = 160) -> str:
    clean = value.strip()
    if (
        not clean
        or len(clean) > maximum
        or any(ord(character) < 32 for character in clean)
    ):
        raise SystemExit(f"{label} must be 1..{maximum} printable characters")
    return clean


def main() -> int:
    args = parse_args()
    budgets_path = args.budgets.expanduser().resolve()
    gate_path = args.gate.expanduser().resolve()
    candidate_dir = args.candidate_dir.expanduser().resolve()
    budgets = load_object(budgets_path, "performance budgets")
    gate = load_object(gate_path, "release gate")
    if budgets.get("schema") != "mterrain-web-performance-budgets-v1":
        raise SystemExit("Unexpected Web performance-budget schema")
    if gate.get("schema") != "mterrain-web-release-gate-v1":
        raise SystemExit("Unexpected Web release-gate schema")

    threshold_digest = threshold_contract_sha256(budgets)
    budgets_digest = sha256(budgets_path)
    gate_digest = sha256(gate_path)
    candidates: dict[str, dict[str, Any]] = {}
    records: list[dict[str, str]] = []
    selected_lanes: set[tuple[str, str]] = set()
    for supplied in args.evidence:
        evidence_path = supplied.expanduser().resolve()
        evidence = load_object(evidence_path, "performance evidence")
        profile = evidence.get("profile")
        lane_name = evidence.get("lane")
        if profile not in ("web_core", "web_extended") or not isinstance(
            lane_name, str
        ):
            raise SystemExit(f"Performance evidence has an invalid identity: {evidence_path}")
        lane_key = (profile, lane_name)
        if lane_key in selected_lanes:
            raise SystemExit(f"Duplicate performance evidence lane: {profile}/{lane_name}")
        selected_lanes.add(lane_key)
        contract = release_gate.profile_contract(gate, profile)
        lane = contract.get("performance_lanes", {}).get(lane_name)
        if not isinstance(lane, dict):
            raise SystemExit(f"Performance evidence names an unknown lane: {profile}/{lane_name}")
        if profile not in candidates:
            candidates[profile] = release_gate.load_candidate(
                candidate_dir,
                profile=profile,
                budgets_sha256=budgets_digest,
                gate_sha256=gate_digest,
            )
        candidate = candidates[profile]
        if not candidate["budget_contract_matches"]:
            raise SystemExit("Candidate release uses a different performance budget")
        if not candidate["release_gate_contract_matches"]:
            raise SystemExit("Candidate release uses a different stable-lane contract")
        if not release_gate.valid_performance_evidence(
            evidence,
            profile=profile,
            lane_name=lane_name,
            lane=lane,
            threshold_digest=threshold_digest,
            budgets_sha256=budgets_digest,
            fixture_contract=budgets["fixture"],
            budget_limits=budgets["profiles"][lane["budget_profile"]],
            candidate=candidate,
        ):
            raise SystemExit(
                f"Evidence is not a passing candidate-bound performance result: "
                f"{evidence_path}"
            )
        records.append(
            {
                "name": evidence_path.name,
                "profile": profile,
                "lane": lane_name,
                "sha256": sha256(evidence_path),
            }
        )

    candidate_versions = {value["version"] for value in candidates.values()}
    candidate_indices = {value["index_sha256"] for value in candidates.values()}
    if len(candidate_versions) != 1 or len(candidate_indices) != 1:
        raise SystemExit("Approved evidence did not resolve to one candidate release")
    records.sort(key=lambda record: (record["profile"], record["lane"]))
    operator = bounded_text(args.operator, "operator")
    report = {
        "schema": "mterrain-web-performance-calibration-v1",
        "status": "reviewed_candidate_bound_evidence",
        "release_gate_eligible": True,
        "threshold_contract_sha256": threshold_digest,
        "candidate_release": {
            "version": next(iter(candidate_versions)),
            "release_index_sha256": next(iter(candidate_indices)),
        },
        "approved_evidence": records,
        "approved_evidence_sha256": [record["sha256"] for record in records],
        "review": {
            "operator": operator,
            "approved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "statement": (
                "I reviewed the named physical-browser performance evidence against "
                "the immutable candidate release and its threshold contract."
            ),
        },
    }
    output = args.output.expanduser().resolve()
    build_root = (ROOT / "build").resolve()
    if output == build_root or build_root not in output.parents:
        raise SystemExit(f"Calibration approval output must be below {build_root}: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    print("MTERRAIN_WEB_PERFORMANCE_CALIBRATION_APPROVED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
