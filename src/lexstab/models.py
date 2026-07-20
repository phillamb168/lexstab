"""Pydantic v2 runtime models for every artifact type (spec §49.2).

These mirror the JSON Schemas in ``schemas/``; both layers validate. Consistency
rules from spec §12.2, §13.5, §15.3–15.5 are enforced as model validators.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.2.0"

OPERATION_ID_PATTERN = r"^[A-Z][A-Z0-9_]+$"
ENTITY_TYPE_PATTERN = r"^[A-Z][A-Z0-9_]+$"
TOOL_PATTERN = r"^[a-z][a-z0-9_]+$"

VARIATION_AXES = [
    "canonical_terminology",
    "entity_synonym",
    "operation_synonym",
    "syntactic_paraphrase",
    "conversational",
    "formal",
    "organizational_jargon",
    "idiomatic",
    "indirect_request",
    "question_form",
    "passive_voice",
    "self_correction",
    "disfluency_preserved",
    "plausible_substitution",
    "pronoun_or_coreference",
    "implicit_argument",
    "missing_entity",
    "missing_operation",
    "missing_required_argument",
    "contradictory_constraints",
    "overloaded_term",
    "context_insufficient",
    "policy_prohibited",
    "high_lexical_distance",
    "minimal_semantic_contrast",
    "typed",
    "spoken_human_transcript",
    "spoken_asr_transcript",
]

ARCHITECTURES = [
    "A0_DIRECT",
    "A1_DIRECT_CLARIFY",
    "B_RUNTIME",
    "B_GOLD",
    "C_RUNTIME",
    "C_GOLD",
    "D_DEFINITION_ONLY",
    "E_ORGANIZATION_TERM",
    "B_EXTERNAL_GATE",
    "B_EXTERNAL_GATE_GOLD",
    "HUMAN_ORACLE",
    "M0_NO_MEMORY",
    "M1_STATIC_GLOSSARY",
    "M2_RETRIEVED_MEMORY",
    "M3_CANONICAL_RESOLVER",
    "M4_PERSONALIZED_MEMORY",
    "P0_RAW_PROPOSAL",
    "P1_CLARIFY_PROPOSAL",
    "P2_CANONICAL_PROPOSAL",
    "P3_CANONICAL_PROCEDURE_PROPOSAL",
    "P4_CANONICAL_PROCEDURE_TOOL",
    "LP0_LANGUAGE_THROUGHOUT",
    "LP0G_GOLD_START_LANGUAGE",
    "LP1_CANONICAL_ONCE",
    "LP2_CANONICAL_PROCEDURE",
    "LP3_CANONICAL_PROCEDURE_TOOL",
]

REPRESENTATION_CLASSES = [
    "FREE_FORM_LANGUAGE",
    "CANONICAL_STATE",
    "CANONICAL_STATE_PLUS_PROCEDURE",
    "TYPED_ACTION_INTERFACE",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- enums


class SemanticRole(str, Enum):
    INVARIANT = "INVARIANT"
    CLARIFICATION = "CLARIFICATION"
    CONTRAST = "CONTRAST"
    REFUSAL = "REFUSAL"


class Adequacy(str, Enum):
    ADEQUATE = "ADEQUATE"
    INADEQUATE = "INADEQUATE"


class Ambiguity(str, Enum):
    UNAMBIGUOUS = "UNAMBIGUOUS"
    AMBIGUOUS = "AMBIGUOUS"


class ExpectedBehavior(str, Enum):
    EXECUTE = "EXECUTE"
    CLARIFY = "CLARIFY"
    REFUSE = "REFUSE"


class LexicalEquivalence(str, Enum):
    INVARIANT = "INVARIANT"
    CONTRAST = "CONTRAST"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ValidationStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    FROZEN = "FROZEN"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class GoldDecision(str, Enum):
    ACT = "ACT"
    CLARIFY = "CLARIFY"
    REFUSE = "REFUSE"


class RenderingCategory(str, Enum):
    CANONICAL_LABEL = "CANONICAL_LABEL"
    MODEL_DISCOVERED = "MODEL_DISCOVERED"
    ORGANIZATION_PREFERRED = "ORGANIZATION_PREFERRED"
    HUMAN_ALTERNATIVE = "HUMAN_ALTERNATIVE"
    DEFINITION_ONLY = "DEFINITION_ONLY"
    OPAQUE_ID_ONLY = "OPAQUE_ID_ONLY"


class InterfaceKind(str, Enum):
    GENERIC_PROPOSAL = "GENERIC_PROPOSAL"
    NATIVE_TOOL = "NATIVE_TOOL"
    MCP_CAPABILITY = "MCP_CAPABILITY"


# ---------------------------------------------------------------- domain


class ArgumentSpec(StrictModel):
    type: Literal["string", "integer", "number", "boolean", "array", "object"]
    required: bool
    pattern: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    enum: list[Any] | None = None
    description: str | None = None


class EntityType(StrictModel):
    schema_version: str = SCHEMA_VERSION
    entity_type: str = Field(pattern=ENTITY_TYPE_PATTERN)
    id_pattern: str
    state_alias: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    collection: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    required_state: dict[str, ArgumentSpec]
    description: str = ""


class Operation(StrictModel):
    schema_version: str = SCHEMA_VERSION
    operation_id: str = Field(pattern=OPERATION_ID_PATTERN)
    display_name: str = Field(min_length=1)
    entity_type: str = Field(pattern=ENTITY_TYPE_PATTERN)
    tool: str = Field(pattern=TOOL_PATTERN)
    arguments: dict[str, ArgumentSpec]
    preconditions: list[str]
    effects: list[str]
    invalid_when: list[str] = Field(default_factory=list)
    primary_contrast: str | None = None
    description: str = ""


class Policy(StrictModel):
    schema_version: str = SCHEMA_VERSION
    policy_id: str = Field(pattern=r"^P-[0-9]+$")
    text: str = Field(min_length=1)
    applies_to_operation_ids: list[str] = Field(default_factory=list)


class DomainFile(StrictModel):
    schema_version: str = SCHEMA_VERSION
    domain: str
    entities: list[EntityType] | None = None
    operations: list[Operation] | None = None
    policies: list[Policy] | None = None


# ---------------------------------------------------------------- cases


class CanonicalIntent(StrictModel):
    entity_type: str = Field(pattern=ENTITY_TYPE_PATTERN)
    entity_id: str
    operation_id: str = Field(pattern=OPERATION_ID_PATTERN)
    arguments: dict[str, Any]


class GoldSpec(StrictModel):
    decision: GoldDecision
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    resulting_state: dict[str, Any] | None = None
    refusal_reason_code: str | None = None
    refusal_policy_id: str | None = None
    clarification_targets: list[str] | None = None

    @model_validator(mode="after")
    def _check_decision(self) -> "GoldSpec":
        if self.decision == GoldDecision.ACT:
            if not self.tool or self.arguments is None:
                raise ValueError("gold decision ACT requires tool and arguments")
            if self.resulting_state is None:
                raise ValueError("gold decision ACT requires resulting_state")
        if self.decision == GoldDecision.REFUSE and not (
            self.refusal_reason_code or self.refusal_policy_id
        ):
            raise ValueError(
                "gold decision REFUSE requires a reason code or policy reference"
            )
        return self


class CanonicalCase(StrictModel):
    schema_version: str = SCHEMA_VERSION
    case_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    domain: str
    title: str = Field(min_length=1)
    family_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    canonical: CanonicalIntent
    initial_state: dict[str, Any]
    gold: GoldSpec
    tags: list[str]
    difficulty: Literal["basic", "intermediate", "advanced"]
    created_by: str
    created_at: str


# ---------------------------------------------------------------- contexts


class ContextMessage(StrictModel):
    role: Literal["user", "assistant", "system"]
    content: str


class FrozenContext(StrictModel):
    schema_version: str = SCHEMA_VERSION
    context_id: str = Field(pattern=r"^CTX-[A-Z0-9-]+$")
    messages: list[ContextMessage]
    visible_state: dict[str, Any] = Field(default_factory=dict)
    available_to_architectures: list[str]
    content_hash: str | None = None


# ---------------------------------------------------------------- requests


class RequestSource(StrictModel):
    type: Literal["human", "synthetic", "redteam"]
    creator: str | None = None
    model_provider: str | None = None
    model_id: str | None = None
    prompt_id: str | None = None
    seed: int | None = None


class RequestLabels(StrictModel):
    semantic_role: SemanticRole
    adequacy: Adequacy
    ambiguity: Ambiguity
    expected_behavior: ExpectedBehavior
    lexical_equivalence: LexicalEquivalence
    missing_information: list[str] = Field(default_factory=list)
    contradiction_reason: str | None = None
    context_id: str | None = None
    variation_axes: list[str] = Field(min_length=1)
    contains_canonical_entity_term: bool = False
    contains_canonical_operation_term: bool = False
    contains_model_discovered_term: bool = False
    contains_organization_term: bool = False
    lexical_distance_band: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    contrast_operation_id: str | None = None
    contrast_arguments: dict[str, Any] | None = None
    refusal_operation_id: str | None = None
    refusal_policy_reference: str | None = None

    @model_validator(mode="after")
    def _consistency(self) -> "RequestLabels":
        for axis in self.variation_axes:
            if axis not in VARIATION_AXES:
                raise ValueError(f"unknown variation axis: {axis}")
        if (
            self.adequacy == Adequacy.INADEQUATE
            and not self.missing_information
            and not self.contradiction_reason
        ):
            raise ValueError(
                "INADEQUATE requires missing_information or contradiction_reason"
            )
        if (
            self.ambiguity == Ambiguity.AMBIGUOUS
            and self.expected_behavior == ExpectedBehavior.EXECUTE
        ):
            raise ValueError("AMBIGUOUS implies CLARIFY (or policy REFUSE), not EXECUTE")
        if self.semantic_role == SemanticRole.REFUSAL:
            if self.expected_behavior != ExpectedBehavior.REFUSE:
                raise ValueError("semantic role REFUSAL requires expected REFUSE")
            if not self.refusal_operation_id or not self.refusal_policy_reference:
                raise ValueError(
                    "REFUSAL must identify the prohibited operation and the "
                    "controlling policy or precondition"
                )
        if self.semantic_role == SemanticRole.CLARIFICATION and (
            self.expected_behavior != ExpectedBehavior.CLARIFY
        ):
            raise ValueError("semantic role CLARIFICATION requires expected CLARIFY")
        if self.semantic_role == SemanticRole.INVARIANT and (
            self.lexical_equivalence != LexicalEquivalence.INVARIANT
        ):
            raise ValueError("semantic role INVARIANT requires lexical INVARIANT")
        if self.semantic_role == SemanticRole.CONTRAST:
            if self.lexical_equivalence != LexicalEquivalence.CONTRAST:
                raise ValueError("semantic role CONTRAST requires lexical CONTRAST")
            if not self.contrast_operation_id:
                raise ValueError("CONTRAST must name its gold contrast operation")
        context_dependent = (
            self.adequacy == Adequacy.INADEQUATE
            or "pronoun_or_coreference" in self.variation_axes
            or "context_insufficient" in self.variation_axes
        )
        if context_dependent and not self.context_id:
            raise ValueError(
                "context-dependent adequacy labels require a frozen context_id"
            )
        return self


class ReviewerDecision(StrictModel):
    reviewer_id: str
    decision: Literal["APPROVE", "REJECT", "EDIT_AND_APPROVE", "NEEDS_SECOND_REVIEW"]
    notes: str = ""
    reviewed_at: str | None = None
    label_assessment: dict[str, str] | None = None


class RequestValidation(StrictModel):
    status: ValidationStatus
    semantic_equivalence: bool | None = None
    adequacy_verified: bool | None = None
    ambiguity_verified: bool | None = None
    reviewers: list[ReviewerDecision] = Field(default_factory=list)
    approved_by: str | None = None
    approved_at: str | None = None
    critic_judgments: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reviewed(self) -> "RequestValidation":
        if self.status in (ValidationStatus.APPROVED, ValidationStatus.FROZEN):
            if not any(
                reviewer.decision in ("APPROVE", "EDIT_AND_APPROVE")
                for reviewer in self.reviewers
            ):
                raise ValueError(
                    f"status {self.status.value} requires at least one approving "
                    "reviewer decision"
                )
        return self


class Provenance(StrictModel):
    created_at: str
    source_run_id: str | None = None
    parent_request_id: str | None = None
    content_hash: str | None = None


class NLRequest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    request_id: str = Field(pattern=r"^REQ-[A-Z0-9-]+$")
    case_id: str
    text: str = Field(min_length=1)
    language: str = "en-US"
    source: RequestSource
    labels: RequestLabels
    validation: RequestValidation
    provenance: Provenance
    audio_uri: str | None = None
    transcript_kind: Literal["typed", "human_transcript", "asr_transcript"] | None = None

    @model_validator(mode="after")
    def _frozen_requires_hash(self) -> "NLRequest":
        if (
            self.validation.status == ValidationStatus.FROZEN
            and not self.provenance.content_hash
        ):
            raise ValueError("frozen requests require a content hash")
        return self

    def is_primary_h1(self) -> bool:
        labels = self.labels
        return (
            labels.adequacy == Adequacy.ADEQUATE
            and labels.ambiguity == Ambiguity.UNAMBIGUOUS
            and labels.expected_behavior == ExpectedBehavior.EXECUTE
            and labels.lexical_equivalence == LexicalEquivalence.INVARIANT
        )


# ---------------------------------------------------------------- renderings


class RenderingDiscovery(StrictModel):
    provider: str
    model_id: str
    prompt_id: str
    sample_count: int
    normalized_label_count: int
    convergence_rate: float
    seed_policy: str
    term_entropy: float | None = None
    discovered_on_split: str | None = "development"


class RenderingValidation(StrictModel):
    status: ValidationStatus
    reviewed_by: list[str] = Field(default_factory=list)
    approved_at: str | None = None


class Rendering(StrictModel):
    schema_version: str = SCHEMA_VERSION
    rendering_id: str = Field(pattern=r"^REN-[A-Z0-9-]+$")
    operation_id: str = Field(pattern=OPERATION_ID_PATTERN)
    entity_type: str = Field(pattern=ENTITY_TYPE_PATTERN)
    category: RenderingCategory
    label: str | None = None
    template: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    discovery: RenderingDiscovery | None = None
    validation: RenderingValidation
    provenance: Provenance

    @model_validator(mode="after")
    def _discovered_needs_provenance(self) -> "Rendering":
        if self.category == RenderingCategory.MODEL_DISCOVERED and not self.discovery:
            raise ValueError("MODEL_DISCOVERED renderings require discovery provenance")
        return self


# ---------------------------------------------------------------- memory


class MemoryScope(StrictModel):
    organization_id: str
    team_id: str | None = None
    user_id: str | None = None


class MemoryCanonicalMapping(StrictModel):
    operation_id: str | None = None
    entity_type: str | None = None
    required_unresolved_arguments: list[str] = Field(default_factory=list)


class SemanticMemoryRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    memory_id: str = Field(pattern=r"^MEM-[A-Z0-9-]+$")
    scope: MemoryScope
    surface_form: str = Field(min_length=1)
    canonical_mapping: MemoryCanonicalMapping
    status: Literal["CONFIRMED", "CANDIDATE", "SUPERSEDED", "RETRACTED"]
    confirmed_by: str | None = None
    effective_from: str
    effective_to: str | None = None
    provenance: dict[str, Any]


# ---------------------------------------------------------------- procedures


class ProcedureStep(StrictModel):
    step_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    instruction: str = Field(min_length=1)


class ProcedureEvaluationContract(StrictModel):
    registered_checks: list[str] = Field(default_factory=list)
    forbidden_operation_ids: list[str] = Field(default_factory=list)
    required_observable_events: list[str] = Field(default_factory=list)


class Procedure(StrictModel):
    schema_version: str = SCHEMA_VERSION
    procedure_id: str = Field(pattern=r"^SKILL_[A-Z0-9_]+$")
    procedure_version: str
    title: str = Field(min_length=1)
    applies_to_operation_ids: list[str] = Field(min_length=1)
    required_inputs: list[str]
    steps: list[ProcedureStep] = Field(min_length=1)
    forbidden_behaviors: list[str] = Field(default_factory=list)
    evaluation_contract: ProcedureEvaluationContract
    output_contract: str
    validation: RenderingValidation
    provenance: dict[str, Any]


# ---------------------------------------------------------------- interfaces


class ActionInterface(StrictModel):
    schema_version: str = SCHEMA_VERSION
    interface_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    interface_version: str
    kind: InterfaceKind
    operation_ids: list[str] = Field(min_length=1)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    argument_schema_hash: str | None = None
    tool_description_hash: str | None = None
    transport: str = "local"
    adapter_version: str = "1"
    validation_behavior: str = "reject_invalid"
    discovery_behavior: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class ActionProposal(StrictModel):
    """generic-action-proposal.v1 output contract (spec §15.5)."""

    decision: GoldDecision
    operation_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    question: str | None = None
    reason_code: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> "ActionProposal":
        if self.decision == GoldDecision.ACT and not self.operation_id:
            raise ValueError("ACT proposals require operation_id")
        return self


# ---------------------------------------------------------------- manifests


class BenchmarkSection(StrictModel):
    files: list[str] = Field(default_factory=list)
    ids: list[str] = Field(default_factory=list)
    hashes: dict[str, str] = Field(default_factory=dict)


class BenchmarkManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    benchmark_id: str
    benchmark_version: str
    created_at: str
    description: str = ""
    artifact_root_hash: str
    ontology: dict[str, Any]
    cases: BenchmarkSection
    requests: BenchmarkSection
    renderings: BenchmarkSection
    procedures: BenchmarkSection
    action_interfaces: BenchmarkSection
    contexts: BenchmarkSection
    semantic_memory: BenchmarkSection
    elicitation_cases: BenchmarkSection = Field(default_factory=BenchmarkSection)
    prompt_versions: dict[str, str]
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    splits: dict[str, list[str]]
    allowed_architectures: list[str]
    validation: dict[str, bool]
    development_overwrite: bool = False
    changelog: list[dict[str, Any]] = Field(default_factory=list)


class RunManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    run_name: str
    created_at: str
    benchmark_manifest_path: str
    benchmark_root_hash: str
    code_revision: str | None
    lockfile_hash: str | None
    resolved_roles: dict[str, Any]
    prompt_hashes: dict[str, str]
    procedure_hashes: dict[str, str] = Field(default_factory=dict)
    interface_hashes: dict[str, str] = Field(default_factory=dict)
    provider_adapter_versions: dict[str, str]
    run_clock: str
    matrix_seed: int
    matrix_cell_count: int
    matrix_hash: str
    tracks: dict[str, Any]
    formalization_conditions: list[str] = Field(default_factory=list)
    persistence_conditions: list[str] = Field(default_factory=list)
    repetitions: int
    concurrency: int
    tracing: dict[str, Any]
    environment: dict[str, str]
    research_overrides: dict[str, Any] = Field(default_factory=dict)
    analysis_plan_hash: str | None = None
    baseline_eligible: bool = True
    mocked: bool = False


# ---------------------------------------------------------------- invocation


class InvocationRecord(StrictModel):
    run_id: str
    cell_id: str
    role: str
    provider: str
    requested_model_id: str
    reported_model_id: str | None = None
    fingerprint: str | None = None
    timestamp: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    response_schema_id: str | None = None
    requested_parameters: dict[str, Any]
    accepted_parameters: dict[str, Any] | None = None
    raw_response: Any
    normalized_text: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_call_mode: Literal["native", "fallback_json", "mock"] | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = None
    cost_estimate: float | None = None
    finish_reason: str | None = None
    provider_request_id: str | None = None
    transport_retries: int = 0
    parse_status: Literal["ok", "error", "empty"] = "ok"
    parse_error: str | None = None
    content_hash: str | None = None
    cached: bool = False


# ---------------------------------------------------------------- scores


class ScoreRecord(StrictModel):
    run_id: str
    cell_id: str
    case_id: str
    request_id: str | None
    architecture: str
    track: str
    repetition: int
    rendering_id: str | None = None
    procedure_id: str | None = None
    interface_id: str | None = None
    model_id: str
    schema_valid: bool
    decision: str | None
    decision_correct: bool
    tool_correct: bool | None
    argument_field_results: dict[str, bool] = Field(default_factory=dict)
    arguments_all_correct: bool | None
    full_call_correct: bool
    final_state_correct: bool | None
    raw_score: dict[str, Any] = Field(default_factory=dict)
    normalized_score: dict[str, Any] = Field(default_factory=dict)
    clarification_outcome: str | None = None
    false_action: bool = False
    refusal_correct: bool | None = None
    contrast_correct: bool | None = None
    error_category: str | None = None
    procedure_adherence: dict[str, Any] | None = None
    interface_errors: list[str] = Field(default_factory=list)
    persistence: dict[str, Any] | None = None
    judge: dict[str, Any] | None = None
    latency_ms: float | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepresentationLedgerRecord(StrictModel):
    run_id: str
    cell_id: str
    stage_id: str
    stage_index: int
    authoritative_representation: str
    canonical_ids_present: bool
    procedure_id_present: bool
    typed_schema_present: bool
    input_content_hash: str
    output_content_hash: str

    @model_validator(mode="after")
    def _check_class(self) -> "RepresentationLedgerRecord":
        if self.authoritative_representation not in REPRESENTATION_CLASSES:
            raise ValueError(
                f"unknown representation class: {self.authoritative_representation}"
            )
        return self


class ComplexityProfile(StrictModel):
    schema_version: str = SCHEMA_VERSION
    architecture: str
    model_invocations_per_task: float
    retrieval_invocations_per_task: float = 0.0
    external_services: list[str] = Field(default_factory=list)
    persisted_stores: list[str] = Field(default_factory=list)
    mutable_model_stages: int = 0
    schema_count: int = 0
    prompt_count: int = 0
    monitoring_surfaces: list[str] = Field(default_factory=list)
    distinct_failure_modes: list[str] = Field(default_factory=list)
    human_review_steps: list[str] = Field(default_factory=list)
    invalidation_procedures: list[str] = Field(default_factory=list)
    procedure_count: int = 0
    interface_dependencies: list[str] = Field(default_factory=list)
    nl_handoff_count: int = 0
    typed_handoff_count: int = 0
    operator_runbook_steps: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- elicitation


class ElicitationCase(StrictModel):
    schema_version: str = SCHEMA_VERSION
    elicitation_case_id: str = Field(pattern=r"^ELICIT-[A-Z0-9-]+$")
    linked_case_id: str
    initial_request_id: str
    gold_initial_labels: dict[str, Any]
    scripted_user_answers: dict[str, str]
    resolved_gold: CanonicalIntent
    maximum_clarification_turns: int = 3
