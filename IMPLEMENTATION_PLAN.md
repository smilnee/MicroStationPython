# V21 Harness Improvement: Implementation Plan

**Audience:** an LLM coding agent (Claude Code, Copilot, or similar) working in the project folder
`C:\Users\Stuart.Milne\Documents\MicroStationBentleyChatbot\` with full read/write access.

**Inputs this plan consolidates:**
- `harnesscapabilitiesanalysis.md` — capability architecture brief
- `LAST_7_REQUESTS_ISSUE_HANDOFF.md` — seven-run failure evidence (P0.x/P1.x/P2.x items)
- `HARNESS_NEUTRALITY_AND_STRATEGY_REVIEW.md` — strategy review and recommendations
- `SOURCE_VERIFIED_FINDINGS.md` — source-verified findings with line anchors (Findings 1–5)

**Primary file:** `MicroStationBentleyChatbotPyQt6V21.py` (~18,500 lines).
**Support modules:** `conversation_artifact_store.py`, `conversation_artifact_processors.py`, `conversation_context_summary.py`, `conversation_context_composer.py`.
**Tests:** `test_v21_regressions.py` (70 tests), `test_v21_context_artifacts.py` (16 tests).
**Benchmark service:** `independent_benchmark_mcp/benchmark_service.py`.

---

## 0. Ground rules for the implementing model

1. **Locate code by symbol, not line number.** Line numbers cited below are from the reviewed revision and will drift. Search for the named function/constant first (e.g. `def _image_attachment_to_data_url`, `MAX_COMPRESSED_IMAGE_BYTES`). If a cited symbol is missing or looks different, stop and re-read the surrounding code before editing — do not guess.
2. **Run the test suite before you start and after every phase:** `python test_v21_regressions.py` and `python test_v21_context_artifacts.py` (or however the project runs them — check for a runner). All 86 existing tests must stay green unless a phase explicitly changes an asserted behavior; in that case update the test in the same change and say so.
3. **One phase per commit** (or per changeset if not using git locally). Keep each phase independently revertible.
4. **Match existing code style** — this codebase uses long descriptive names, f-strings, `log_event(...)` structured telemetry, and defensive `try/except`. Add new telemetry through the existing `log_event` mechanism, not `print`.
5. **Do not touch the neutral core with MicroStation-specific policy.** Runtime contracts, recipes, and MicroStation validation belong in the Model Tool Access / MicroStation capability paths only. This invariant already exists in the codebase ("Already Fixed" section of the handoff) — preserve it.
6. **Do not reopen the already-fixed items:** validation-receipt/script fingerprint binding, invalid active-model accessor rejection, `ModelInfo.GetUorPerMaster()` rejection, capability-owned (not neutral-core) runtime contracts.
7. **Preserve persisted settings compatibility.** Capability keys, config JSON shape, and conversation/artifact schemas must keep loading old data. Additive schema changes only.
8. **Terminology:** "candidate" = the model being tested; "controller/evaluator" = harness-owned benchmark machinery; "neutral core" = code paths active with all capabilities off.

**Recommended phase order** (dependencies noted per phase):
Phase 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13.
Phases 1–3 restore measurement validity and are prerequisites for trusting any later testing. Phase 4 (crash deny-list) is small and should land before any live MicroStation testing. If time is limited, Phases 1–7 deliver most of the quality gain.

---

## Phase 1 — Image fidelity (Finding 1; Review rec. 3)

**Problem.** `_image_attachment_to_data_url` (near line 8092) crushes every image to ≤1024 px / ≤60 KB JPEG (quality 68→32, grayscale variant tried) unless `request_profile_name == "geometry-build"`. The good path (1568 px long edge, PNG preserved for drawing-like images, 4 MB cap) exists at the top of the same function. Files >20 MB (`MAX_ATTACHMENT_IMAGE_BYTES`) are silently dropped.

**Changes.**
1. In `_image_attachment_to_data_url`, make the current geometry-build branch the **universal** encoding path:
   - Remove the `if self.request_profile_name == "geometry-build":` condition so the 1568 px / PNG-for-drawings / 4 MB logic runs for every profile.
   - Delete the fallback loop over `ATTACHMENT_IMAGE_DIMENSIONS` × `ATTACHMENT_IMAGE_JPEG_QUALITIES` and the grayscale variant, or keep it only as a last-resort fallback if the 4 MB budget cannot be met at 1568 px (in that case step 1568→1280→1024 at q88→q80→q72, never below 1024/q68 — still far above 60 KB).
   - Read the existing `build_image_quality` config for `long_edge`, `jpeg_quality`, `png_for_drawings`, `max_bytes` so users can tune it; keep current defaults (1568 / 88 / true / 4194304).
2. Delete or repurpose `MAX_COMPRESSED_IMAGE_BYTES = 60 * 1024` and `ATTACHMENT_IMAGE_JPEG_QUALITIES = (68, 54, 42, 32)`. Grep for other users before deleting.
3. **No silent drops.** Where the function currently returns `""` (file >20 MB, decode failure, over-budget), instead:
   - `log_event("attachment_image_omitted", reason=..., path=..., byte_count=...)`
   - Surface a visible warning via the existing progress/status mechanism (`self.progress.emit(...)`) and, if a message list is shown to the user per request, add "Image X was not sent to the model (reason)".
4. **Telemetry for every sent image:** `log_event("attachment_image_encoded", name=..., source_w=..., source_h=..., sent_w=..., sent_h=..., sent_bytes=..., format=...)`. This is the permanent guard against regression to thumbnail-crushing.

**Acceptance.**
- A 3000×2000 px, 2 MB house-plan PNG attached in bare Chat produces a sent image ≥1568 px long edge, PNG format (it is drawing-like), logged with final dimensions.
- No code path can send an image under 100 KB unless the source itself is that small.
- A 25 MB image produces a user-visible warning and an `attachment_image_omitted` event, not silence.

**Tests to add** (in `test_v21_regressions.py` style): encode a synthetic 3000×2000 line-drawing PNG through the function with a default-profile worker stub; assert output data-URL decodes to ≥1568 px and mime `image/png`; assert the omitted-event path fires for an oversized file.

---

## Phase 2 — Context fidelity (Finding 2, Finding 5; Review rec. 4)

**Problem.** History reaching the model is 6 messages × 1,200 chars (default profile) / 4 × 4,000 total (geometry-build); tool results truncated to 5,000 chars; the composer assumes a 96k context window when provider metadata is missing; the deterministic summarizer misclassifies every post-first user message as a "constraint".

**Changes.**
1. In the constants block (near lines 244–316) and `REQUEST_PROFILES` (near 444):
   - `MAX_MODEL_HISTORY_MESSAGES`: 6 → **40**.
   - Per-message truncation in `build_compact_conversation_context` (near 4905): 1,200 → **8,000** chars; attachment text in history 500 → 2,000 chars.
   - `MAX_COMPRESSED_CONTEXT_CHARS`: 8,000 → **60,000**.
   - `geometry-build` profile: `history_messages` 4 → 20, `history_chars` 4,000 → 30,000, `tool_chars` 5,000 → **20,000** (tool-result fidelity matters most in this profile).
   - `code` profile: raise proportionally (e.g. 10 / 15,000 / 10,000).
2. Make these budget-aware rather than unconditional: after raising the constants, if the composed request would exceed the provider input budget (use the existing `compute_budget` / `conversation_context_composer.compute_budget`), degrade gracefully by dropping **oldest** history first — never by re-truncating individual recent messages harder.
3. In `conversation_context_composer.py`: `DEFAULT_CONTEXT_WINDOW` 96,000 → **200,000**, and populate real per-model limits where the provider layer knows them (`normalize_provider_metadata` already accepts `contextWindowTokens` — ensure callers pass it from model discovery metadata when available; keep `limitsAssumed` flagging).
4. In `conversation_context_summary.py`, `_classify_user_text`: stop treating every later user message as a constraint. Only append to `userConstraints` when the text matches constraint-like intent (imperatives such as "must", "always", "never", "don't", "use only", "keep"); otherwise record it in provenance only. Allow objective revision: if a later user message starts with a re-scoping phrase ("instead", "actually", "change of plan", "new task"), replace `userObjective`.
5. Keep the summarizer deterministic (it is a neutrality asset — do not convert it to an LLM pass).

**Acceptance.**
- A 30-turn conversation replayed through `build_compact_conversation_context` retains ≥20 recent messages verbatim (subject to provider budget).
- With provider metadata for a 200k model, `compute_budget(...).remainingTokens` is positive for a 50k-token composed request.
- Summary fixture: a conversation where turn 5 says "actually, make it a garage instead" ends with `userObjective` reflecting the garage, and "thanks, looks good" never appears in `userConstraints`.

**Tests:** update any existing tests that assert the old limits (they exist — search for `1200`, `8000`, `history_messages`); add the three acceptance fixtures above to `test_v21_context_artifacts.py`.

---

## Phase 3 — Payload transparency + golden-payload regression (Review recs. 1–2)

**Problem.** Neutrality is currently argued from code reading. Make it observable and regression-tested.

**Changes.**
1. Add a config flag `payload_transparency` (default off) to the chatbot config (`get_default_chatbot_config`). When on, immediately before every provider POST (there appears to be one chokepoint — `_post_model_streaming`; verify all request paths go through it, including the image-planning pass and phase execution), write one JSONL record to `logs/payloads.jsonl`:
   `{run_id, turn, model, system_chars, message_count, messages: [{role, chars, image_count, image_dims}], tool_schema_count, tool_names, reasoning_effort, max_completion_tokens, temperature}`.
   Store full message **text** only when a second flag `payload_transparency_full` is on (privacy default: shapes and sizes only).
2. Golden-payload test: construct a bare-Chat `ChatWorker` (all capabilities false, Chat mode, empty system prompt file) with prompt "P" and one small PNG; intercept the payload (refactor so `run_minimal_chat` builds the payload via a testable `_build_minimal_payload()` helper, or capture via the transparency hook); assert:
   - exactly one system message or none; if present it contains only user-set system prompt text and/or the compact-context block;
   - the user message contains exactly "P" plus the attachment framing lines and the image part;
   - `tools` absent/empty; no MicroStation-related string constants anywhere in the payload (assert on a deny-list: "MicroStation", "MCP", "Build mode", "DGN").
3. Also assert the **image-planning** payload (when that capability is on) contains only the documented planning system prompt — this keeps future prompt drift visible.

**Acceptance.** The golden test fails if anyone later adds a single injected sentence to bare Chat. Payload JSONL appears for every model turn when enabled, including tool-loop turns.

---

## Phase 4 — Crash deny-list and runtime contracts (P0.1, P1.1)

**Problem.** Static validation passed four runtime-invalid scripts, one of which (`SolidUtil.Convert.BodyToElement` with a fresh `EditElementHandle()` template) crashed MicroStation.

**Where.** The MicroStation Model Tool Access validation path — find the existing capability-owned runtime-contract code (the handoff says invalid-active-model and `ModelInfo.GetUorPerMaster` rejections already live there; search for `GetUorPerMaster` in the client to find the module/function). Extend that same mechanism; do not add MicroStation policy to the neutral core.

**Changes.** Add contracts (AST-based where possible, regex fallback) rejecting before execution, each with a specific diagnostic naming the API and the safe alternative:
1. **Unsafe BodyToElement template:** any `SolidUtil.Convert.BodyToElement(...)` whose 3rd argument (`templateEh`) is a direct constructor call `EditElementHandle()` (or a name assigned from a bare `EditElementHandle()` with no element loaded). Diagnostic: "BodyToElement requires a live template element or element ID; pass an existing element (see samples) or use ISolidPrimitive.CreateDgnBox → DraftingElementSchema.ToElement → AddToModel." (Verified: MSPy binding is `BodyToElement(eeh, entity, templateEh, modelRef)`; all Bentley samples pass a live element.)
2. **Uninitialized DRange3d output:** `DRange3d()` default-constructed then passed to `GetRange(...)` — direct the script to the documented range-query pattern from the recipe (Phase 10).
3. **Run-2 unit idiom:** the exact `storage.ConvertDistanceFrom(info.GetUorPerStorage(), master)` shape; direct to `GetUorPerMaster(modelRef)` static (verified to exist on the model-ref class) or the recipe's unit block.
4. Treat native-kernel conversion APIs (`SolidUtil.Convert.*`, `SolidUtil.Create.BodyFrom*`) as high-risk: allowed only when the call shape matches a verified recipe signature; otherwise reject with the safe-route diagnostic.

**Regression fixtures:** add all seven benchmark-run scripts verbatim (evidence directories listed in the handoff) as fixtures with expected accept/reject results: runs 2, 4, 5, 6 rejected with their specific diagnostics; the known-good `DraftingElementSchema.ToElement` scripts from runs 1 and 3 accepted. Assert a non-MicroStation tool path is unaffected.

**Acceptance (from handoff P0.1/P1.1).** The exact run-4 script is rejected pre-execution with a diagnostic naming `SolidUtil.Convert.BodyToElement`; known-good scripts still pass; unrelated providers/tools unaffected.

---

## Phase 5 — Executor feedback fidelity (P1.2) + read-only de-quarantine (P1.3)

These are the two highest-value behavior fixes. Do them together; they touch the same result-handling code.

### 5a. Never collapse errors (P1.2)
**Where.** The client-side handling of `microstation_run_python` results and the mutation-outcome classification (search `mcp_mutation_outcome_indeterminate`, `runtimeError`, `Unknown exception` handling).

**Changes.**
1. Build a structured failure record for every failed tool execution and pass it **verbatim** into the tool-result message the model sees (subject to the raised `tool_chars` from Phase 2): all available stderr, structured content, `returnValue`, request ID, script fingerprint, elapsed time, and before/after element-count observations when the harness has them.
2. Add a failure classifier producing one of: `python-exception`, `binding-type-error`, `native-exception`, `transport-failure`, `timeout`, `host-termination`, `unknown`. Base it only on available evidence (exception text patterns, fault-log correlation for host termination, transport errors from the MCP client). **Never invent a traceback**; when the executor supplies nothing, say exactly that: "The secure executor returned no diagnostic detail (classification: unknown). The operation may or may not have partially executed."
3. Add a **diagnostic wrapper template** for read-only probes: a capability-owned helper that generates probe scripts wrapping each step in its own try/except and serializing per-step results/exceptions into `__result__`, so a single bad call no longer produces a top-level executor failure. Expose it in the prepare-time capability context (Phase 10) as the recommended probe pattern.

### 5b. Effect classification; quarantine only mutators (P1.3)
**Where.** Wherever a failed/indeterminate mutation currently zeroes the tool list (search for the code that recomputes context with `tool_count: 0` after `mcp_mutation_outcome_indeterminate`).

**Changes.**
1. Classify every verified MicroStation script before execution as `read-only`, `mutation-capable`, or `unknown`:
   - `read-only` if it contains no write-capable API pattern (maintain a list: `AddToModel`, `ReplaceInModel`, `DeleteFromModel`, `ToElement(`, `SolidUtil.Convert`, level/model/file mutation calls, key-in execution) — conservative allow-list of pure query patterns is acceptable as v1.
   - `mutation-capable` if any write pattern present; `unknown` otherwise.
2. On failure:
   - `read-only` failure → **no quarantine at all**; the model keeps every tool and gets the Phase 5a failure record.
   - `mutation-capable`/`unknown` failure with indeterminate commit state → withhold **mutating tools only**; retain `microstation_prepare_python`, all lookup tools, `microstation_verify_python_code`, read-only `microstation_execute_query`, and `microstation_capture_viewport`.
   - If before/after observations show no state change, downgrade an `unknown` to effectively read-only and lift the restriction.
3. Log classification + reason + exact retained tool subset: `log_event("script_effect_classified", classification=..., reason=..., retained_tools=[...])`.
4. Tell the model what happened in the next turn's context: "The previous script failed; mutating tools are withheld because the commit state is unknown. Diagnostic and read-only tools remain available."

**Acceptance (handoff).** A failed unit/range probe still permits preparation, lookups, verification, read-only query, and a corrected probe. A genuinely mutation-capable unknown failure restricts mutators only. Tests: replay run-5 and run-6 probe scripts through the classifier (both `read-only`); assert full tool retention after simulated failure; assert a run-1-style build script classifies `mutation-capable`.

---

## Phase 6 — Build prompt rewrite + orchestration pressure removal (Finding 3)

**Problem.** The ~600-word geometry-build system prompt bans model API knowledge, bans diagnostic probing, orders stop-on-opaque-error, contradicts itself on lookups, contains stale "V19" text, and an execute-immediately nudge injects synthetic user messages.

**Where.** `_run_chat_direct` system-parts assembly (search for the string "Geometry build profile is active"), the Plan/Build/Code mode strings nearby, and the planning-indicator nudge (search for `"i will call"`).

**Changes.**
1. Replace the geometry-build block with roughly this (≤12 lines, adjust wording to taste but preserve intent):
   ```text
   Geometry build profile is active. Objective: create the most detailed reliable model the
   prompt, attachments, and active model context support; use conceptual detail only if asked.
   You may draw on your own MicroStation Python knowledge; verify it by running small scripts
   before large ones — validation is advisory and execution is the test. A canonical prepared
   recipe (units, levels, box creation, add-to-model, range query) is provided in context;
   prefer it over rediscovery. Workflow: inspect state if needed → smoke-test one element →
   build in stages → verify with read-only queries → capture the viewport. After a failure,
   read the diagnostic, correct, and retry; use read-only probes freely. If the commit state
   of a mutation is unknown, verify with a read-only query before repeating it.
   Scripts must set __result__ = json.dumps({ok, createdElementIds, createdCount, failedCount,
   assumptions}). Report what changed and what evidence supports it.
   ```
   Explicitly deleted: the from-memory ban, "never run diagnostic Python", "stop immediately", the lookup-timing contradiction, the V19 sentence, detail-level meta-discussion (keep `requested_detail_level` handling in code, one short sentence in prompt), and 6 of the 11 required JSON fields (keep `ok, createdElementIds, createdCount, failedCount, assumptions`; make the rest optional).
2. Delete the execute-immediately nudge (the `planning` indicator list and injected synthetic user message), or gate it to fire only after **two** consecutive no-tool-call narration turns, with the injected message reworded to a system-role note ("Reminder: you can call tools directly in this turn."). Never inject as `role: user`.
3. Verify `MAX_RUNTIME_REPAIRS` (currently 6) is still enforced in code, not prompt — repair budget is fine as a code-level guard.
4. Keep the "No MicroStation tools were initialized" honesty block (it's good), and keep Plan/Chat strings as they are (they're already minimal).

**Acceptance.** New prompt ≤~150 words; golden-payload test from Phase 3 extended with a Build-mode variant asserting the deleted phrases ("from memory", "stop immediately", "never run diagnostic") no longer appear in any payload. A narration-only model turn no longer triggers an immediate synthetic user message.

---

## Phase 7 — Tool budgets, terminal reasons, verification reserve (P2.2; Review §3.3)

**Where.** `DEFAULT_NON_AGENTIC_TOOL_TURNS` (6), `MAX_LLM_TOOL_TURNS` (20), `CapabilitySnapshot.max_tool_turns`, the tool-loop turn accounting in `run_tool_chat`/`_run_chat_direct`.

**Changes.**
1. Raise defaults: non-agentic 6 → **16**; agentic 20 → **48**. Make both configurable in the chatbot config.
2. **Visible budget:** include in the tool-loop system context each turn: "Tool turns used: N of M. A reserve of R read-only turns is guaranteed for verification and capture."
3. **Verification reserve:** hold back R=3 turns usable only for read-only tools (query, capture, verify). When the general budget is exhausted, don't zero the tool list — swap to the read-only subset for the reserve turns, then do the final tool-free synthesis turn.
4. **Terminal reason:** single enum recorded and shown to both the model (final-turn context) and the report: `budget-exhausted`, `safety-quarantine`, `capability-disabled`, `provider-tool-mismatch`, `completed`. Fix the run-6 class of misreporting (model said "budget exhausted" when the true cause was quarantine at 10/12 calls).
5. Late exploratory lookups must not consume the reserve (enforced by the reserve mechanism itself).

**Acceptance (handoff).** Final reports identify the actual reason tools disappeared; a successful build retains ≥3 read-only turns for verification/capture. Test: simulate exhaustion and quarantine separately; assert distinct terminal reasons and reserve availability.

---

## Phase 8 — Provider timeout resilience (P2.1)

**Where.** `_post_model_streaming` (180 s timeout) and its callers.

**Changes.**
1. Log a `model_turn_timeout` event with endpoint, elapsed, and whether any stream data arrived.
2. Retry a timed-out read **once** when no mutating tool call is in flight (the harness knows the last executed tool's classification from Phase 5b), with jittered backoff. Never retry when a mutation's commit state is unknown.
3. Distinguish idle/read timeout from total turn duration for streaming: if tokens are actively arriving, don't kill at 180 s; use an inter-chunk idle timeout (e.g. 60 s) plus a generous total cap (e.g. 600 s), both configurable.
4. On terminal failure, return a useful partial result: completed discovery/tool log summary + "no write occurred" (or last known state), instead of only "Request failed: The read operation timed out". Preserve benchmark finalization (already works — don't break it).

**Acceptance (handoff).** A simulated stalled response produces one bounded retry, an explicit timeout classification, no duplicate tool execution, and a finalized benchmark with a useful partial response.

---

## Phase 9 — Benchmark run integrity (P0.2, P0.3)

**Where.** `independent_benchmark_mcp/benchmark_service.py` + the client-side benchmark lifecycle calls (search `benchmark_start_run`).

**Changes.**
1. **Stale-run reconciliation (P0.2):** persist `{owner_pid, owner_run_id, heartbeat_at}` with each running benchmark; heartbeat periodically. On service/client startup and before `benchmark_start_run`, finalize any `running` record without a live owner as `crashed` (or `aborted`), preserving partial pre-state, event evidence, and correlating the fault log by timestamp. Atomic state updates (write-temp-then-replace, as the artifact store already does).
2. **Clean-baseline enforcement (P0.3):** before candidate invocation, verify baseline: `clean_baseline` true **and** record baseline identity as a DGN file hash, not just element count. If dirty: either restore the known clean DGN (config points at a golden copy) or fail the run before the model is invoked. Cleanup is controller-owned — never a candidate-visible tool or instruction.
3. **Status field split (P1.8):** replace the single status with four fields — `lifecycle` (`running|finalized|aborted`), `request` (`succeeded|failed|timed_out|crashed`), `task` (`passed|failed|not_assessed`), `evidence` (`complete|partial|invalid`). Migrate readers; keep writing the legacy field for old tooling if anything parses it.

**Acceptance (handoff).** Kill the client during `microstation_run_python` → after restart the run is terminal with a crash reason and `post_state` unavailable; a dirty file blocks or is restored before `benchmark_start_run` completes; a zero-build graceful response is `lifecycle: finalized, task: failed`.

---

## Phase 10 — Evaluator correctness (P1.5, P1.6, P1.7)

**Where.** Controller capture code (`_controller_capture_build_views` and the evaluator's standard-view calls) and benchmark scoring.

**Changes.**
1. **Standard-view capture (P1.5):** debug the evaluator's view-setting call against the running MicroStation version (all four of Front/Right/Top/Iso failed identically — likely one schema/command mismatch, e.g. key-in vs tool schema or view-index argument). Verify each view change with a read-back before capturing; record the concrete tool response per attempt. Fallback: fitted current view when a standard orientation fails. Report `captures_attempted` vs `captures_valid` separately. Decide and document whether valid candidate captures may supplement controller captures (recommended: yes, labeled `candidate-supplied`, never replacing controller captures for independence-critical scoring).
2. **Actor attribution (P1.6):** tag every tool call with an actor: `candidate`, `controller-observation`, `evaluator`, `lifecycle`. `candidate operational success` computes only over candidate-owned calls; evaluator collection reported separately; overall benchmark validity may fail on missing evidence without blaming the candidate.
3. **Task-quality metrics (P1.7):** structural delta alone never sets task quality. Add evaluator-owned checks: overall extents vs expected envelope, nondegenerate ranges/volumes, expected spatial zones, facade/interior coverage. Fix `box_like_element_count` to recognize `Solid` elements produced from `DgnBoxDetail`. Report ranges in master units with adequate precision; flag near-zero dimensions. `task_quality` is `not_assessed` (never null) without valid visual or geometric evidence.

**Acceptance (handoff).** A simple box model yields four nonblank, distinct, correctly oriented captures with roles; a structurally successful candidate with failed controller captures reports candidate success separately from evaluator evidence failure; a pile of arbitrary boxes passes structural integrity but not task quality.

---

## Phase 11 — Canonical recipe + knowledge grounding (P1.4, P2.3, P2.4; Review §3.5)

**Changes.**
1. **Author one canonical, tested MicroStation build recipe** injected into the capability context returned by `microstation_prepare_python` (client-side prepare-context assembly if the MCP can't change). Contents (all verified against MSPy source):
   - Active model + units: `ISessionMgr.ActiveDgnModelRef`; UOR-per-master via the model-ref static `GetUorPerMaster(modelRef)` (NOT `ModelInfo.GetUorPerMaster()`, which does not exist).
   - Box: `DgnBoxDetail` → `ISolidPrimitive.CreateDgnBox(data)` → `DraftingElementSchema.ToElement(eeh, primitive, None, model.Is3d(), model)` → set level/color via `ElementPropertiesSetter` → `eeh.AddToModel()`.
   - Level lookup/creation pattern (safe: get level cache, find-or-create named level) so builds stop landing everything on one level (P2.3): recommended categories `shell`, `internal-walls`, `glazing`, `doors`, `roof`, `furniture`, `site`.
   - Range query pattern with a properly initialized output (the Phase 4 contract's positive example).
   - Read-only probe wrapper template (Phase 5a).
   - The convergence rule as guidance: prepare → ≤2 lookups → one-box smoke test → scale up.
2. **Verify the recipe end-to-end once manually in MicroStation** before shipping it (create box, query it, delete it). The recipe must be executable fact, not documentation.
3. **Evidence-honesty guidance (P2.4):** add one line to the Build prompt (Phase 6 text already hints): final responses must distinguish `captured`, `visually inspected by model`, and `independently benchmarked`; never claim visual fidelity without image analysis. Add a lightweight response check: if the final text claims visual verification but no capture/image-analysis tool ran, append a correction note to the report.
4. Ground lookups in the `.pyi` stubs: if lookup tools are client-implemented, index `MSPythonSamples/Intellisense/*.pyi` for deterministic signature answers before semantic search. (The samples contain **no** box-primitive example — semantic lookup cannot find one; the recipe is the only reliable source.)

**Acceptance (handoff P1.4).** From a clean model, a candidate creates and verifies one box within four tool calls, then completes the full build without further API discovery.

---

## Phase 12 — Capability hygiene (Review rec. 5–6; brief's Managed Build question)

**Changes.**
1. **Retire `enhanced_build`:** no runtime consumer exists. Keep the key loading for config compatibility; remove the UI toggle or mark it "(legacy, no effect)".
2. **Resolve `managed_build`:** trace `_managed_build` branches from `ChatWorker.__init__`, `_run_chat`, `_run_chat_direct`, `run_tool_chat`, `_run_controller_build_pipeline`, `_simple_build` (note: dispatch shows `mode==Build and use_mcp and _managed_build and not _simple_build` → `_run_controller_build_pipeline`). Decide: either document it as a supported alternative pipeline with a test proving reachability, or excise the dead branches. Don't leave it ambiguous.
3. **Profiles in the UI:** present four presets over the 15 keys — `Bare` (all off), `Tools` (mcp_available + microstation_tools + model_tool_access), `Tools+Safety` (+require_change_confirmation + advanced_verification), `Full`. Keep individual toggles under an "advanced" expander. Persist as the same 15 keys.
4. **Publish mode templates:** show the exact Chat/Plan/Build/Code injected strings read-only in settings so "what does this mode inject" never requires reading source.

---

## Phase 13 — Validation: the honest experiment + ablation matrix

After Phases 1–11 land, run the measurement program (this is the point of everything above):

1. **Bare-vision test:** bare Chat + house PNG + "Describe this building precisely: overall dimensions, rooms, openings, roof form." Compare against the pre-fix behavior; archive the payload JSONL proving image fidelity.
2. **Minimal-harness build test:** bare Code mode + house PNG → run the generated script manually in MicroStation. This measures model knowledge + clean image with zero tool ceremony. (Expect this to be surprisingly good once the knowledge ban is gone.)
3. **Ablation matrix:** same model, same prompt, same clean baseline (Phase 9 guarantees it), sweeping profiles: Bare → Tools → Tools+recipe (Phase 11) → Tools+Safety → Full, × 2–3 models. Use the fixed evaluator (Phase 10) for scoring. Keep a capability only if it measurably improves task quality or safety.
4. **Regression suite completion** (handoff list): seven-run script corpus (Phase 4), native-crash reconciliation (Phase 9), dirty-baseline block (Phase 9), read-only failed-probe tool retention (Phase 5), mutation-unknown restriction (Phase 5), actor attribution (Phase 10), four-view capture (Phase 10), stream-timeout bounded retry (Phase 8), box/range metrics (Phase 10), end-to-end house smoke test: clean baseline → one-box probe → full build → structural delta → four valid visual roles → finalized benchmark.

---

## Quick-reference: symbol → phase map

| Symbol / location | Phase |
|---|---|
| `_image_attachment_to_data_url`, `MAX_COMPRESSED_IMAGE_BYTES`, `ATTACHMENT_IMAGE_*` | 1 |
| `build_compact_conversation_context`, `MAX_MODEL_HISTORY_MESSAGES`, `REQUEST_PROFILES`, `DEFAULT_CONTEXT_WINDOW` (composer), `_classify_user_text` (summary) | 2 |
| `_post_model_streaming` (hook), `run_minimal_chat`, `get_default_chatbot_config` | 3 |
| MicroStation runtime-contract module (search `GetUorPerMaster` rejection) | 4 |
| `mcp_mutation_outcome_indeterminate` handling, tool-result assembly | 5 |
| "Geometry build profile is active" string, `"i will call"` nudge list | 6 |
| `DEFAULT_NON_AGENTIC_TOOL_TURNS`, `MAX_LLM_TOOL_TURNS`, `run_tool_chat` loop | 7 |
| `_post_model_streaming` timeout(s) | 8 |
| `benchmark_service.py`, `benchmark_start_run` callers | 9 |
| `_controller_capture_build_views`, evaluator scoring | 10 |
| prepare-context assembly, Build prompt (again), `.pyi` index | 11 |
| `enhanced_build` / `_managed_build` branches, capability UI | 12 |

## Verified API facts the implementer may rely on (from the MicroStationPython repo)

- `SolidUtil.Convert.BodyToElement(eeh, entity, templateEh, modelRef)` — binding at `MSPythonWrapper/PyMstnPlatform/source/PSolid/psolidcoreapi.cpp:1318`; every Bentley sample passes a live element/ID as `templateEh`.
- `ModelInfo.GetUorPerMaster()` does not exist; a static `GetUorPerMaster(modelRef)` binding exists on the model-ref class (`msdgnmodelref.cpp:641`).
- `ISolidPrimitive.CreateDgnBox(data: DgnBoxDetail)` exists (intellisense stub `MSPyBentleyGeom.pyi:42310`); no sample demonstrates it — the recipe is the only reliable delivery mechanism.
- Deterministic API index: `MSPythonSamples/Intellisense/*.pyi`.
