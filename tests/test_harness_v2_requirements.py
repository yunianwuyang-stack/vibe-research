from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import unicodedata
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "harness" / "v2" / "scripts" / "requirements.py"
SPEC = importlib.util.spec_from_file_location("harness_v2_requirements", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
requirements = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(requirements)


def _json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def inputs() -> tuple[str, dict, dict, dict]:
    guide = (ROOT / requirements.GUIDE_PATH).read_text(encoding="utf-8")
    manifest = _json(requirements.MANIFEST_PATH)
    checker_policy = _json(requirements.CHECKER_POLICY_PATH)
    evaluator_policy = _json(requirements.EVALUATOR_POLICY_PATH)
    return guide, manifest, checker_policy, evaluator_policy


def _build(
    inputs: tuple[str, dict, dict, dict],
    guide: str | None = None,
    *,
    manifest: dict | None = None,
    checker_policy: dict | None = None,
    evaluator_policy: dict | None = None,
) -> dict:
    source, base_manifest, base_checker_policy, base_evaluator_policy = inputs
    return requirements.build_registry(
        source if guide is None else guide,
        copy.deepcopy(base_manifest if manifest is None else manifest),
        copy.deepcopy(base_checker_policy if checker_policy is None else checker_policy),
        copy.deepcopy(base_evaluator_policy if evaluator_policy is None else evaluator_policy),
    )


@pytest.mark.parametrize("status", ["implemented", "qualified"])
def test_bootstrap_checker_implementation_binding_is_preserved_and_spec_bound(
    inputs: tuple[str, dict, dict, dict], status: str
) -> None:
    baseline = _build(inputs)
    policy = copy.deepcopy(inputs[2])
    entry = policy["bootstrap_checkers"][0]
    entry.update(
        {
            "implementation_status": status,
            "implementation_path": "harness/v2/scripts/baseline.py",
            "implementation_hash": "a" * 64,
        }
    )

    registry = _build(inputs, checker_policy=policy)
    checker = next(
        item for item in registry["checker_registry"] if item["id"] == "CHK-REQ-P0-01"
    )

    assert checker["implementation_status"] == status
    assert checker["implementation_path"] == "harness/v2/scripts/baseline.py"
    assert checker["implementation_hash"] == "a" * 64
    assert registry["requirements_spec_hash"] != baseline["requirements_spec_hash"]


def test_implemented_checker_and_task_bindings_rehash_real_files(
    tmp_path: Path, inputs: tuple[str, dict, dict, dict]
) -> None:
    implementation = tmp_path / "harness" / "v2" / "scripts" / "checker.py"
    contract = tmp_path / "harness" / "v2" / "contracts" / "P0-CHECK.json"
    implementation.parent.mkdir(parents=True)
    contract.parent.mkdir(parents=True)
    implementation.write_text("print('checker')\n", encoding="utf-8")
    contract.write_text(
        json.dumps({"id": "P0-CHECK", "requirement_ids": ["REQ-P0-01"]}),
        encoding="utf-8",
    )
    policy = copy.deepcopy(inputs[2])
    policy["bootstrap_checkers"][0].update(
        {
            "implementation_status": "implemented",
            "implementation_path": "harness/v2/scripts/checker.py",
            "implementation_hash": hashlib.sha256(implementation.read_bytes()).hexdigest(),
        }
    )
    manifest = copy.deepcopy(inputs[1])
    manifest["bootstrap_tasks"] = [
        {
            "id": "P0-CHECK",
            "requirement_ids": ["REQ-P0-01"],
            "registration_status": "implemented",
            "source": "test-contract",
            "contract_path": "harness/v2/contracts/P0-CHECK.json",
            "contract_hash": hashlib.sha256(contract.read_bytes()).hexdigest(),
        }
    ]
    registry = _build(inputs, manifest=manifest, checker_policy=policy)

    requirements._validate_external_bindings(tmp_path, registry)

    implementation.write_text("print('tampered')\n", encoding="utf-8")
    with pytest.raises(requirements.RequirementError, match="checker implementation hash drift"):
        requirements._validate_external_bindings(tmp_path, registry)


def test_actual_guide_freezes_exactly_90_requirements_to_tmp_path(tmp_path: Path) -> None:
    output = tmp_path / "requirements.json"
    lock = tmp_path / "requirements.lock.json"

    registry, lock_payload = requirements.freeze(ROOT, output=output, lock_output=lock)

    assert registry["requirement_count"] == 90
    assert len(registry["requirements"]) == 90
    assert registry["requirements"][0]["id"] == "REQ-P0-01"
    assert registry["requirements"][-1]["id"] == "REQ-DOD-18"
    assert all(item["state"] == "NOT_RUN" for item in registry["requirements"])
    assert requirements.validate(ROOT, requirements=output, lock=lock) == registry["requirements_spec_hash"]
    assert lock_payload["requirements_spec_hash"] == registry["requirements_spec_hash"]
    assert lock_payload["requirements_document_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_section_12_progress_text_is_not_spec_bound(inputs: tuple[str, dict, dict, dict]) -> None:
    guide = inputs[0]
    baseline = _build(inputs)
    marker = "### Progress"
    changed = guide.replace(marker, marker + "\n\n- machine progress entry without a requirement", 1)

    updated = _build(inputs, changed)

    assert updated["requirements_spec_hash"] == baseline["requirements_spec_hash"]
    assert updated["source"]["normalized_guide_sha256"] != baseline["source"]["normalized_guide_sha256"]
    assert (
        updated["source"]["normalized_non_living_guide_sha256"]
        == baseline["source"]["normalized_non_living_guide_sha256"]
    )


def test_non_requirement_prose_outside_frozen_fields_is_not_spec_bound(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    baseline = _build(inputs)
    changed = inputs[0].replace(
        "## 1. \u5f53\u524d\u9879\u76ee\u6df1\u5ea6\u5ba1\u8ba1",
        "## 1. \u5f53\u524d\u9879\u76ee\u6df1\u5ea6\u9759\u6001\u5ba1\u8ba1",
        1,
    )

    assert changed != inputs[0]
    updated = _build(inputs, changed)
    assert updated["requirements_spec_hash"] == baseline["requirements_spec_hash"]
    assert (
        updated["source"]["normalized_non_living_guide_sha256"]
        != baseline["source"]["normalized_non_living_guide_sha256"]
    )


def test_section_12_concrete_requirement_mentions_are_excluded_from_spec(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    guide = inputs[0]
    marker = "### Progress"
    changed = guide.replace(marker, marker + "\n\n- `REQ-P0-01` must not be redefined here", 1)

    baseline = _build(inputs)
    updated = _build(inputs, changed)
    assert updated["requirements_spec_hash"] == baseline["requirements_spec_hash"]
    assert (
        updated["source"]["normalized_non_living_guide_sha256"]
        == baseline["source"]["normalized_non_living_guide_sha256"]
    )


@pytest.mark.parametrize("mutation", ["renamed", "duplicate"])
def test_section_12_h2_is_unique_and_exact(
    inputs: tuple[str, dict, dict, dict], mutation: str
) -> None:
    guide = inputs[0]
    if mutation == "renamed":
        changed = guide.replace("## 12. Living Document", "## 12. Progress Log", 1)
    else:
        changed = guide.replace(
            "## 13. Goal \u6a21\u5f0f\u542f\u52a8",
            "## 12. Living Document\n\n## 13. Goal \u6a21\u5f0f\u542f\u52a8",
            1,
        )

    with pytest.raises(requirements.RequirementError, match="must appear exactly once with exact title"):
        _build(inputs, changed)


def test_concrete_requirement_after_section_12_is_still_rejected(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    marker = "## 13. Goal \u6a21\u5f0f\u542f\u52a8"
    changed = inputs[0].replace(marker, marker + "\n\n`REQ-P0-01` outside the living subtree", 1)

    with pytest.raises(requirements.RequirementError, match="outside a definition block"):
        _build(inputs, changed)


def test_line_endings_and_terminal_whitespace_are_normalized(inputs: tuple[str, dict, dict, dict]) -> None:
    baseline = _build(inputs)
    crlf = inputs[0].replace("\n", "\r\n") + "\r\n\r\n"

    assert _build(inputs, crlf)["requirements_spec_hash"] == baseline["requirements_spec_hash"]


@pytest.mark.parametrize("variant", ["bom", "cr", "trailing-tab"])
def test_source_normalization_variants_are_hash_invariant(
    inputs: tuple[str, dict, dict, dict], variant: str
) -> None:
    guide = inputs[0]
    if variant == "bom":
        changed = "\ufeff" + guide
    elif variant == "cr":
        changed = guide.replace("\n", "\r")
    else:
        changed = guide.replace("\n", "\t\n")

    baseline = _build(inputs)
    updated = _build(inputs, changed)
    assert updated["requirements_spec_hash"] == baseline["requirements_spec_hash"]
    assert updated["source"]["normalized_guide_sha256"] == baseline["source"]["normalized_guide_sha256"]
    assert (
        updated["source"]["normalized_non_living_guide_sha256"]
        == baseline["source"]["normalized_non_living_guide_sha256"]
    )


def test_nfc_and_nfd_source_are_hash_invariant(inputs: tuple[str, dict, dict, dict]) -> None:
    composed = inputs[0].replace("# Vibe Research", "# Vib\u00e9 Research", 1)
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed

    nfc_registry = _build(inputs, composed)
    nfd_registry = _build(inputs, decomposed)
    assert nfd_registry["requirements_spec_hash"] == nfc_registry["requirements_spec_hash"]
    assert nfd_registry["source"] == nfc_registry["source"]


def test_requirement_completion_change_changes_spec_hash(inputs: tuple[str, dict, dict, dict]) -> None:
    baseline = _build(inputs)
    changed = inputs[0].replace(
        "\u6240\u6709 preexisting \u6587\u4ef6\u53ef\u5f52\u5c5e\u4e14\u672a\u4e22\u5931",
        "\u6240\u6709 preexisting \u6587\u4ef6\u53ef\u5f52\u5c5e\u3001\u6709 hash \u4e14\u672a\u4e22\u5931",
        1,
    )

    assert changed != inputs[0]
    assert _build(inputs, changed)["requirements_spec_hash"] != baseline["requirements_spec_hash"]


def test_guide_threshold_change_changes_spec_hash(inputs: tuple[str, dict, dict, dict]) -> None:
    baseline = _build(inputs)
    changed = inputs[0].replace("<=12s", "<=13s", 1)

    assert changed != inputs[0]
    assert _build(inputs, changed)["requirements_spec_hash"] != baseline["requirements_spec_hash"]


def test_duplicate_definition_is_rejected(inputs: tuple[str, dict, dict, dict]) -> None:
    changed = inputs[0].replace("`REQ-P0-02`", "`REQ-P0-01`", 1)

    with pytest.raises(requirements.RequirementError, match="duplicate requirement"):
        _build(inputs, changed)


def test_phase_requirement_source_order_is_exact(inputs: tuple[str, dict, dict, dict]) -> None:
    changed = inputs[0].replace("`REQ-P0-01`", "`REQ-P0-TEMP`", 1)
    changed = changed.replace("`REQ-P0-02`", "`REQ-P0-01`", 1)
    changed = changed.replace("`REQ-P0-TEMP`", "`REQ-P0-02`", 1)

    with pytest.raises(requirements.RequirementError, match="source order"):
        _build(inputs, changed)


def test_dod_requirement_must_be_direct_ordered_list_item(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    changed = inputs[0].replace("1. `REQ-DOD-01`", "`REQ-DOD-01`", 1)

    with pytest.raises(requirements.RequirementError, match="direct ordered-list item"):
        _build(inputs, changed)


@pytest.mark.parametrize("mutation", ["id-order", "marker-ordinal"])
def test_dod_source_order_and_ordinal_are_exact(
    inputs: tuple[str, dict, dict, dict], mutation: str
) -> None:
    guide = inputs[0]
    if mutation == "id-order":
        changed = guide.replace("`REQ-DOD-01`", "`REQ-DOD-TEMP`", 1)
        changed = changed.replace("`REQ-DOD-02`", "`REQ-DOD-01`", 1)
        changed = changed.replace("`REQ-DOD-TEMP`", "`REQ-DOD-02`", 1)
    else:
        changed = guide.replace("2. `REQ-DOD-02`", "1. `REQ-DOD-02`", 1)

    with pytest.raises(requirements.RequirementError, match="source order/ordinal mismatch"):
        _build(inputs, changed)


def test_wildcard_definition_is_rejected(inputs: tuple[str, dict, dict, dict]) -> None:
    changed = inputs[0].replace("`REQ-P0-01`", "`REQ-P0-*`", 1)

    with pytest.raises(requirements.RequirementError, match="wildcard"):
        _build(inputs, changed)


def test_hidden_markdown_reference_cannot_bypass_full_document_scan(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    marker = "## 12. Living Document"
    changed = inputs[0].replace(
        marker,
        "[hidden-requirement]: https://invalid.example/REQ-P0-01\n\n" + marker,
        1,
    )

    with pytest.raises(requirements.RequirementError, match="outside a definition block"):
        _build(inputs, changed)


@pytest.mark.parametrize(
    "payload",
    [
        "<!-- REQ-P0-01 -->",
        '<div data-requirement="REQ-P0-01"></div>',
        "[hidden](https://invalid.example/REQ-P0-01)",
        "```text\nREQ-P0-01\n```",
    ],
    ids=["comment", "html", "link-destination", "fence"],
)
def test_hidden_markdown_forms_cannot_bypass_full_document_scan(
    inputs: tuple[str, dict, dict, dict], payload: str
) -> None:
    marker = "## 11. \u6700\u7ec8 Definition of Done"
    changed = inputs[0].replace(marker, payload + "\n\n" + marker, 1)

    with pytest.raises(requirements.RequirementError, match="outside a definition block"):
        _build(inputs, changed)


def test_unicode_confusable_requirement_id_is_rejected(inputs: tuple[str, dict, dict, dict]) -> None:
    marker = "## 11. \u6700\u7ec8 Definition of Done"
    changed = inputs[0].replace(marker, "`\uff32\uff25\uff31\uff0d\uff30\uff10\uff0d\uff10\uff11`\n\n" + marker, 1)

    with pytest.raises(requirements.RequirementError, match="confusable requirement ID"):
        _build(inputs, changed)


def test_numbering_gap_is_rejected(inputs: tuple[str, dict, dict, dict]) -> None:
    changed = inputs[0].replace("`REQ-P0-02`", "`REQ-P0-08`", 1)

    with pytest.raises(requirements.RequirementError, match="frozen 90-ID plan|numbering gap"):
        _build(inputs, changed)


def test_orphan_requirement_without_task_mapping_is_rejected(inputs: tuple[str, dict, dict, dict]) -> None:
    registry = _build(inputs)
    registry["requirements"][0]["task_ids"] = []

    with pytest.raises(requirements.RequirementError, match="task_ids must not be empty"):
        requirements.validate_registry_payload(registry)


def test_checker_policy_requires_complete_exact_default_schema(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    policy = copy.deepcopy(inputs[2])
    del policy["default_mapping"]["missing_checker_behavior"]

    with pytest.raises(requirements.RequirementError, match="checker default_mapping schema mismatch"):
        _build(inputs, checker_policy=policy)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("verdict_source", "manual_pass"),
        ("missing_checker_behavior", "pass"),
        ("missing_receipt_behavior", "pass"),
        ("unknown_status_behavior", "manual_pass"),
    ],
)
def test_checker_policy_rejects_fail_open_default_semantics(
    inputs: tuple[str, dict, dict, dict], field: str, value: str
) -> None:
    policy = copy.deepcopy(inputs[2])
    policy["default_mapping"][field] = value

    with pytest.raises(requirements.RequirementError, match="exactly fail-closed"):
        _build(inputs, checker_policy=policy)


@pytest.mark.parametrize(
    "control",
    [
        "invalidate_prior_receipts",
        "require_independent_diff_review",
        "require_positive_control",
        "require_fault_injection_control",
    ],
)
def test_checker_change_controls_cannot_be_disabled(
    inputs: tuple[str, dict, dict, dict], control: str
) -> None:
    policy = copy.deepcopy(inputs[2])
    policy["checker_change_policy"][control] = False

    with pytest.raises(requirements.RequirementError, match="change controls"):
        _build(inputs, checker_policy=policy)


def test_p0_checker_algorithm_and_shortcuts_are_frozen(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    weakened_algorithm = copy.deepcopy(inputs[2])
    weakened_algorithm["bootstrap_checkers"][0]["algorithm"] = "return pass"
    with pytest.raises(requirements.RequirementError, match="algorithm drift"):
        _build(inputs, checker_policy=weakened_algorithm)

    removed_shortcut = copy.deepcopy(inputs[2])
    removed_shortcut["bootstrap_checkers"][0]["forbidden_shortcuts"].pop()
    with pytest.raises(requirements.RequirementError, match="forbidden-shortcut drift"):
        _build(inputs, checker_policy=removed_shortcut)


def test_evaluator_policy_requires_complete_registration_schema(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    missing_top_level = copy.deepcopy(inputs[3])
    del missing_top_level["registration_required_fields"]
    with pytest.raises(requirements.RequirementError, match="evaluator policy schema mismatch"):
        _build(inputs, evaluator_policy=missing_top_level)

    missing_field = copy.deepcopy(inputs[3])
    missing_field["registration_required_fields"].remove("sample_size_calculation")
    with pytest.raises(requirements.RequirementError, match="complete frozen field set"):
        _build(inputs, evaluator_policy=missing_field)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("alpha_max", "disabled"),
        ("power_min", -99),
        ("claim_precision_wilson_lower", 0.94),
        ("open_enabled_core_findings_max", 999999),
        ("audit_coverage", 0.99),
        ("cold_start_seconds_max", 13),
    ],
)
def test_evaluator_policy_rejects_wrong_type_or_weakened_threshold(
    inputs: tuple[str, dict, dict, dict], field: str, value: object
) -> None:
    policy = copy.deepcopy(inputs[3])
    policy["global_thresholds"][field] = value

    with pytest.raises(requirements.RequirementError, match="evaluator threshold"):
        _build(inputs, evaluator_policy=policy)


def test_evaluator_tiers_and_unfrozen_failure_state_are_exact(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    tiers = copy.deepcopy(inputs[3])
    tiers["evaluation_tiers"] = ["PUBLIC", "EXTERNAL_SEALED"]
    with pytest.raises(requirements.RequirementError, match="three-tier"):
        _build(inputs, evaluator_policy=tiers)

    fail_open = copy.deepcopy(inputs[3])
    fail_open["unfrozen_thresholds_fail_as"] = "VERIFIED_PASS"
    with pytest.raises(requirements.RequirementError, match="INSUFFICIENT_EVIDENCE"):
        _build(inputs, evaluator_policy=fail_open)


@pytest.mark.parametrize("registry_name", ["checker_registry", "evaluator_registry"])
def test_checker_and_evaluator_entries_cannot_be_empty_shells(
    inputs: tuple[str, dict, dict, dict], registry_name: str
) -> None:
    registry = _build(inputs)
    registry[registry_name][7]["algorithm"] = ""

    with pytest.raises(requirements.RequirementError, match="frozen fail-closed definition"):
        requirements.validate_registry_payload(registry)


def test_registry_entries_freeze_missing_implementation_and_receipt_behavior(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    checker = _build(inputs)
    checker["checker_registry"][7]["missing_implementation_behavior"] = "pass"
    with pytest.raises(requirements.RequirementError, match="frozen fail-closed definition"):
        requirements.validate_registry_payload(checker)

    evaluator = _build(inputs)
    evaluator["evaluator_registry"][7]["missing_receipt_behavior"] = "pass"
    with pytest.raises(requirements.RequirementError, match="frozen fail-closed definition"):
        requirements.validate_registry_payload(evaluator)


@pytest.mark.parametrize(
    ("reverse_name", "entry_id"),
    [
        ("checker_to_requirements", "CHK-REQ-P0-01"),
        ("evaluator_to_requirements", "EVAL-REQ-P0-01"),
        ("task_to_requirements", "TASK-P0"),
    ],
)
def test_missing_reverse_mapping_is_rejected(
    inputs: tuple[str, dict, dict, dict], reverse_name: str, entry_id: str
) -> None:
    registry = _build(inputs)
    del registry["traceability"][reverse_name][entry_id]

    with pytest.raises(requirements.RequirementError, match="keys mismatch|reverse mapping"):
        requirements.validate_registry_payload(registry)


@pytest.mark.parametrize("state", ["RUNNING", "MYSTERY", "VERIFIED_PASS", "BLOCKED_FINAL"])
def test_frozen_registry_rejects_every_non_initial_state(
    inputs: tuple[str, dict, dict, dict], state: str
) -> None:
    registry = _build(inputs)
    registry["requirements"][0]["state"] = state

    with pytest.raises(requirements.RequirementError, match="must remain NOT_RUN"):
        requirements.validate_registry_payload(registry)


@pytest.mark.parametrize("receipt_id", ["forged", "missing/receipt.json", "0" * 64])
def test_frozen_registry_rejects_any_receipt_id(
    inputs: tuple[str, dict, dict, dict], receipt_id: str
) -> None:
    registry = _build(inputs)
    registry["requirements"][0]["receipt_ids"] = [receipt_id]

    with pytest.raises(requirements.RequirementError, match="cannot contain receipt IDs"):
        requirements.validate_registry_payload(registry)


def test_hash_drift_is_rejected(inputs: tuple[str, dict, dict, dict]) -> None:
    registry = _build(inputs)
    registry["requirements"][0]["completion_text"] += " changed"

    with pytest.raises(requirements.RequirementError, match="requirements_spec_hash drift"):
        requirements.validate_registry_payload(registry)


def test_registry_policy_and_trace_edge_changes_are_spec_hash_bound(
    inputs: tuple[str, dict, dict, dict]
) -> None:
    baseline = _build(inputs)
    baseline_hash = requirements.canonical_sha256(requirements.spec_projection(baseline))

    registry_change = copy.deepcopy(baseline)
    registry_change["checker_registry"][7]["algorithm"] += " changed"
    assert requirements.canonical_sha256(requirements.spec_projection(registry_change)) != baseline_hash

    policy_change = copy.deepcopy(baseline)
    policy_change["registry_policies"]["checker"]["checker_change_policy"][
        "require_positive_control"
    ] = False
    assert requirements.canonical_sha256(requirements.spec_projection(policy_change)) != baseline_hash

    edge_change = copy.deepcopy(baseline)
    edge_change["traceability"]["requirement_to_dod"]["REQ-P0-01"].append("REQ-DOD-17")
    assert requirements.canonical_sha256(requirements.spec_projection(edge_change)) != baseline_hash


def test_dod_and_dependency_edges_are_exact_bidirectional_maps(inputs: tuple[str, dict, dict, dict]) -> None:
    registry = _build(inputs)
    traceability = registry["traceability"]

    assert all(traceability["requirement_to_dod"][requirement_id] for requirement_id in requirements.STAGE_IDS)
    assert all(traceability["dod_to_requirements"][requirement_id] for requirement_id in requirements.DOD_IDS)
    assert requirements._invert(traceability["requirement_to_dod"], requirements.DOD_IDS) == traceability[
        "dod_to_requirements"
    ]
    assert requirements._invert(
        traceability["requirement_dependencies"], requirements.EXPECTED_IDS
    ) == traceability["requirement_required_by"]


def test_cli_freeze_and_validate_use_only_explicit_tmp_outputs(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "requirements.json"
    lock = tmp_path / "nested" / "requirements.lock.json"
    common = [
        "--root",
        str(ROOT),
        "--requirements",
        str(output),
        "--lock",
        str(lock),
    ]

    assert requirements.main(["freeze", *common]) == 0
    assert requirements.main(["validate", *common]) == 0
    assert output.is_file()
    assert lock.is_file()
