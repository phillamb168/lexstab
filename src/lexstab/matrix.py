"""Matrix expansion (spec §18.2).

Produces a stable ordered list of cells with deterministic globally unique IDs
and a matrix hash. Randomized order uses the recorded seed; cell identity never
depends on execution order.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from lexstab import models
from lexstab.config import RunConfig
from lexstab.freeze import FrozenBenchmark
from lexstab.hashing import canonical_json, sha256_text

BOUNDARY_ARCHS = {"A0_DIRECT", "A1_DIRECT_CLARIFY", "B_RUNTIME", "C_RUNTIME"}
POST_CANONICAL_ARCHS = {"B_GOLD", "C_GOLD", "D_DEFINITION_ONLY", "E_ORGANIZATION_TERM"}
INTENT_ARCHS = {"A0_DIRECT", "A1_DIRECT_CLARIFY", "B_EXTERNAL_GATE", "B_EXTERNAL_GATE_GOLD"}
MEMORY_ARCHS = {"M0_NO_MEMORY", "M1_STATIC_GLOSSARY", "M2_RETRIEVED_MEMORY", "M3_CANONICAL_RESOLVER", "M4_PERSONALIZED_MEMORY"}
P_CONDITIONS = ["P0_RAW_PROPOSAL", "P1_CLARIFY_PROPOSAL", "P2_CANONICAL_PROPOSAL",
                "P3_CANONICAL_PROCEDURE_PROPOSAL", "P4_CANONICAL_PROCEDURE_TOOL"]
LP_CONDITIONS = ["LP0_LANGUAGE_THROUGHOUT", "LP0G_GOLD_START_LANGUAGE", "LP1_CANONICAL_ONCE",
                 "LP2_CANONICAL_PROCEDURE", "LP3_CANONICAL_PROCEDURE_TOOL"]
AGENT_LOOP_CONDITIONS = ["AL_RAW", "AL_CANONICAL", "AL_RENDERED", "AL_DRIFT"]

RENDERING_CATEGORY_FOR_ARCH = {
    "C_RUNTIME": "CANONICAL_LABEL",
    "C_GOLD": "CANONICAL_LABEL",
    "D_DEFINITION_ONLY": "DEFINITION_ONLY",
    "E_ORGANIZATION_TERM": "ORGANIZATION_PREFERRED",
}


@dataclass(frozen=True)
class MatrixCell:
    cell_id: str
    track: str
    architecture: str
    case_id: str
    request_id: str | None
    rendering_id: str | None
    procedure_id: str | None
    interface_id: str | None
    intent_mode: str  # "runtime" | "gold" | "none"
    procedure_selection: str  # "gold" | "runtime" | "none"
    procedure_packaging: str  # "inline" | "packaged" | "none"
    repetition: int
    model_role: str
    elicitation_case_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "track": self.track,
            "architecture": self.architecture,
            "case_id": self.case_id,
            "request_id": self.request_id,
            "rendering_id": self.rendering_id,
            "procedure_id": self.procedure_id,
            "interface_id": self.interface_id,
            "intent_mode": self.intent_mode,
            "procedure_selection": self.procedure_selection,
            "procedure_packaging": self.procedure_packaging,
            "repetition": self.repetition,
            "model_role": self.model_role,
            "elicitation_case_id": self.elicitation_case_id,
        }


@dataclass
class Matrix:
    cells: list[MatrixCell]
    matrix_hash: str
    skipped: list[dict] = field(default_factory=list)

    def ordered(self, randomize: bool, seed: int) -> list[MatrixCell]:
        if not randomize:
            return list(self.cells)
        rng = random.Random(seed)
        cells = list(self.cells)
        rng.shuffle(cells)
        return cells


def _cell_id(parts: list[Any]) -> str:
    body = "|".join("" if part is None else str(part) for part in parts)
    return "cell-" + sha256_text(body)[7:23]


def select_cases(bench: FrozenBenchmark, config: RunConfig) -> list[str]:
    split = config.selection.get("split") or "development"
    case_ids = list(bench.manifest.splits.get(split, []))
    explicit = config.selection.get("case_ids") or []
    if explicit:
        case_ids = [cid for cid in case_ids if cid in explicit] or [
            cid for cid in explicit if cid in bench.cases
        ]
    limit = config.selection.get("limit_cases")
    if limit:
        case_ids = case_ids[: int(limit)]
    return case_ids


def _filter_requests(
    requests: list[models.NLRequest], config: RunConfig
) -> list[models.NLRequest]:
    selection = config.selection
    out = []
    for request in requests:
        labels = request.labels
        if selection.get("request_ids") and request.request_id not in selection["request_ids"]:
            continue
        if selection.get("variation_axes") and not (
            set(selection["variation_axes"]) & set(labels.variation_axes)
        ):
            continue
        if selection.get("adequacy") and labels.adequacy.value not in selection["adequacy"]:
            continue
        if selection.get("ambiguity") and labels.ambiguity.value not in selection["ambiguity"]:
            continue
        if selection.get("expected_behavior") and (
            labels.expected_behavior.value not in selection["expected_behavior"]
        ):
            continue
        out.append(request)
    return sorted(out, key=lambda r: r.request_id)


def expand_matrix(bench: FrozenBenchmark, config: RunConfig, model_role: str = "execution_primary") -> Matrix:
    cells: list[MatrixCell] = []
    skipped: list[dict] = []
    case_ids = select_cases(bench, config)
    repetitions = config.repetitions
    tracks = config.tracks

    def add(track, arch, case_id, request_id, *, rendering=None, procedure=None,
            interface=None, intent_mode="none", selection_mode="none", packaging="none",
            elicitation=None):
        for repetition in range(repetitions):
            parts = [track, arch, case_id, request_id, rendering, procedure, interface,
                     intent_mode, selection_mode, packaging, repetition, model_role, elicitation]
            cells.append(
                MatrixCell(
                    cell_id=_cell_id(parts),
                    track=track,
                    architecture=arch,
                    case_id=case_id,
                    request_id=request_id,
                    rendering_id=rendering,
                    procedure_id=procedure,
                    interface_id=interface,
                    intent_mode=intent_mode,
                    procedure_selection=selection_mode,
                    procedure_packaging=packaging,
                    repetition=repetition,
                    model_role=model_role,
                    elicitation_case_id=elicitation,
                )
            )

    def rendering_for(arch: str, operation_id: str) -> str | None:
        category = RENDERING_CATEGORY_FOR_ARCH.get(arch)
        if category is None:
            return None
        rendering = bench.rendering_for_operation(operation_id, category)
        return rendering.rendering_id if rendering else None

    # ---------------- boundary track
    boundary = tracks.get("boundary", {})
    if boundary.get("enabled"):
        for arch in boundary.get("architectures", []):
            for case_id in case_ids:
                case = bench.cases[case_id]
                for request in _filter_requests(bench.requests_for_case(case_id), config):
                    rendering = rendering_for(arch, case.canonical.operation_id)
                    if arch.startswith("C_") and rendering is None:
                        skipped.append({"reason": "no rendering", "architecture": arch, "case_id": case_id})
                        continue
                    add("boundary", arch, case_id, request.request_id,
                        rendering=rendering,
                        intent_mode="runtime" if arch in ("B_RUNTIME", "C_RUNTIME") else "none")

    # ---------------- post-canonical track (gold injection; request optional §25.5)
    post = tracks.get("post_canonical", {})
    if post.get("enabled"):
        for arch in post.get("architectures", []):
            for case_id in case_ids:
                case = bench.cases[case_id]
                if case.gold.decision.value != "ACT":
                    continue  # gold injection needs an executable canonical case
                rendering = rendering_for(arch, case.canonical.operation_id)
                if arch in RENDERING_CATEGORY_FOR_ARCH and rendering is None:
                    skipped.append({"reason": "no rendering", "architecture": arch, "case_id": case_id})
                    continue
                add("post_canonical", arch, case_id, None, rendering=rendering, intent_mode="gold")

    # ---------------- intent elicitation track
    intent = tracks.get("intent_elicitation", {})
    if intent.get("enabled"):
        for arch in intent.get("architectures", []):
            for elicitation_id, ecase in sorted(bench.elicitation.items()):
                if ecase.linked_case_id not in case_ids:
                    continue
                add("intent_elicitation", arch, ecase.linked_case_id, ecase.initial_request_id,
                    intent_mode="gold" if arch == "B_EXTERNAL_GATE_GOLD" else "runtime",
                    elicitation=elicitation_id)

    # ---------------- memory ablation track
    memory = tracks.get("memory_ablation", {})
    if memory.get("enabled"):
        for arch in memory.get("architectures", []):
            for case_id in case_ids:
                for request in _filter_requests(bench.requests_for_case(case_id), config):
                    add("memory_ablation", arch, case_id, request.request_id)

    # ---------------- progressive formalization track
    formal = tracks.get("progressive_formalization", {})
    if formal.get("enabled"):
        conditions = formal.get("conditions", P_CONDITIONS)
        persistence = formal.get("persistence_conditions", LP_CONDITIONS)
        ablations = bool(formal.get("run_component_ablations", True))
        generic_id = "GENERIC_ACTION_PROPOSAL_V1"
        typed_id = "TYPED_SUPPORT_TOOLS_V1"

        for case_id in case_ids:
            case = bench.cases[case_id]
            procedure = bench.procedure_for_operation(case.canonical.operation_id)
            procedure_id = procedure.procedure_id if procedure else None
            for request in _filter_requests(bench.requests_for_case(case_id), config):
                # Primary ladder requests must be adequate and unambiguous (§33.10);
                # inadequate requests run separately for clarification observation.
                for condition in conditions:
                    if condition not in P_CONDITIONS:
                        continue
                    needs_procedure = condition in (
                        "P3_CANONICAL_PROCEDURE_PROPOSAL", "P4_CANONICAL_PROCEDURE_TOOL"
                    )
                    if needs_procedure and procedure_id is None:
                        skipped.append({"reason": "no procedure", "architecture": condition, "case_id": case_id})
                        continue
                    interface = typed_id if condition == "P4_CANONICAL_PROCEDURE_TOOL" else generic_id
                    intent_modes = ["runtime"]
                    if condition in ("P2_CANONICAL_PROPOSAL", "P3_CANONICAL_PROCEDURE_PROPOSAL",
                                     "P4_CANONICAL_PROCEDURE_TOOL") and ablations:
                        intent_modes.append("gold")
                    for mode in intent_modes:
                        add("progressive_formalization", condition, case_id, request.request_id,
                            procedure=procedure_id if needs_procedure else None,
                            interface=interface,
                            intent_mode=mode if condition not in ("P0_RAW_PROPOSAL", "P1_CLARIFY_PROPOSAL") else "none",
                            selection_mode="gold" if needs_procedure else "none",
                            packaging="inline" if needs_procedure else "none")
                    if condition == "P3_CANONICAL_PROCEDURE_PROPOSAL" and ablations and procedure_id:
                        # packaging ablation (§33.9 item 5) and runtime selection (§33.8)
                        add("progressive_formalization", condition, case_id, request.request_id,
                            procedure=procedure_id, interface=generic_id, intent_mode="gold",
                            selection_mode="gold", packaging="packaged")
                        add("progressive_formalization", condition, case_id, request.request_id,
                            procedure=procedure_id, interface=generic_id, intent_mode="gold",
                            selection_mode="runtime", packaging="inline")
            if formal.get("run_language_persistence_ablation", True):
                for request in _filter_requests(bench.requests_for_case(case_id), config):
                    if request.labels.expected_behavior.value != "EXECUTE":
                        continue
                    for condition in persistence:
                        if condition not in LP_CONDITIONS:
                            continue
                        needs_procedure = condition in ("LP2_CANONICAL_PROCEDURE", "LP3_CANONICAL_PROCEDURE_TOOL")
                        if needs_procedure and procedure_id is None:
                            skipped.append({"reason": "no procedure", "architecture": condition, "case_id": case_id})
                            continue
                        interface = typed_id if condition == "LP3_CANONICAL_PROCEDURE_TOOL" else generic_id
                        if condition == "LP0_LANGUAGE_THROUGHOUT":
                            modes = ["runtime"]
                        elif condition == "LP0G_GOLD_START_LANGUAGE":
                            modes = ["gold"]
                        elif condition == "LP1_CANONICAL_ONCE":
                            modes = ["gold", "runtime"]  # D-027: gold primary, runtime practical
                        else:
                            modes = ["gold"]
                        for mode in modes:
                            add("progressive_formalization", condition, case_id, request.request_id,
                                procedure=procedure_id if needs_procedure else None,
                                interface=interface, intent_mode=mode,
                                selection_mode="gold" if needs_procedure else "none",
                                packaging="inline" if needs_procedure else "none")

    # ---------------- agent loop track (Experiment 3)
    agent_loop = tracks.get("agent_loop", {})
    if agent_loop.get("enabled"):
        conditions = agent_loop.get("conditions", AGENT_LOOP_CONDITIONS)
        for case_id in agent_loop.get("case_ids") or case_ids:
            if case_id not in bench.cases:
                continue
            case = bench.cases[case_id]
            rendering = bench.rendering_for_operation(case.canonical.operation_id, "CANONICAL_LABEL")
            for request in _filter_requests(bench.requests_for_case(case_id), config):
                if request.labels.expected_behavior.value != "EXECUTE":
                    continue
                for condition in conditions:
                    add("agent_loop", condition, case_id, request.request_id,
                        rendering=rendering.rendering_id if (rendering and condition == "AL_RENDERED") else None,
                        intent_mode="runtime")

    ordered = sorted(cells, key=lambda cell: cell.cell_id)
    matrix_hash = sha256_text(canonical_json([cell.to_dict() for cell in ordered]))
    return Matrix(cells=ordered, matrix_hash=matrix_hash, skipped=skipped)
