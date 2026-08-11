# Harness Neutrality and Strategy Review

**Scope and evidence basis.** This review is based on: (1) the capability analysis brief (`harnesscapabilitiesanalysis.md`), (2) the seven-run issue handoff (`LAST_7_REQUESTS_ISSUE_HANDOFF.md`), and (3) direct inspection of the MicroStationPython repository source (MSPy wrapper bindings, samples, and intellisense stubs). The chatbot source itself (`MicroStationBentleyChatbotPyQt6V21.py` and its sibling modules) was **not** readable from this environment — it lives on the local PC, and this session runs in a remote container scoped to the `smilnee/MicroStationPython` repository. Claims about harness internals are therefore drawn from the brief and flagged where they need source-level confirmation. API-level claims below were verified against the actual MSPy source.

---

## 1. Is the bare harness (all 15 capabilities off) neutral?

**Short answer: structurally close to neutral in Chat mode, but there are four channels through which influence can leak, and none of them are governed by the capability switches — so "all capabilities off" does not by itself prove neutrality.**

The brief establishes that bare Chat takes a one-request minimal path (`run_minimal_chat`): no MCP, no tools, no skills, no image planning, no phasing, no mutation authority. That is the right skeleton. But the following remain active with everything off, and each can shape model behavior:

### 1.1 The system prompt (highest risk)
The bare harness includes an "editable and persisted system prompt." Neutrality lives or dies here. If the shipped default contains *any* MicroStation framing ("You are an assistant inside MicroStation…"), the bare harness is not neutral — the model will bias toward CAD interpretations of ambiguous prompts, hedge about capabilities it doesn't have, or volunteer MicroStation workflows. **Audit item:** confirm the default system prompt is empty (or purely operational, e.g. formatting), and that a user-edited prompt is clearly displayed as non-default.

### 1.2 Mode templates (definitely not neutral in Code mode)
Mode selection (Chat/Plan/Build/Code) exists outside the capability system. By the brief's own description:

- **Code mode is explicitly MicroStation-flavored even bare** — it "generates a MicroStation Python script and saves it under the configured scripts location." That requires an injected instruction telling the model to produce MSPy code. That is harness influence, by design.
- **Plan mode** presumably injects "produce a plan" instructions — mild but real framing.
- **Build mode** grants authority with no mechanism; if it injects any "you may make changes" language, the model may narrate changes it cannot make.

So the accurate statement is: *bare Chat is (probably) neutral; bare Plan/Build/Code are intentionally non-neutral by mode template.* If the goal is a provably neutral baseline, that baseline is bare Chat specifically, and the mode templates should be audited as part of the harness, not treated as outside it.

### 1.3 The rolling summarizer (a hidden second model pass)
Rolling structured summaries of older history are themselves LLM output inserted into context. Two neutrality risks: (a) the summarizer's prompt may impose structure/vocabulary (e.g. CAD-flavored section headings) that colors later turns; (b) summarization is lossy — dimensions, tolerances, and exact names from early turns can silently degrade. For a long build-from-image session, a summarized early turn that contained the measured dimensions is a real failure mode. **Audit items:** read the summarizer prompt for domain framing; confirm summarization only triggers when genuinely near budget, not eagerly; confirm exact-evidence artifacts are actually retrieved when the summary references them.

### 1.4 The image rendition pipeline (directly relevant to the house test)
The bare harness produces "derived thumbnails and model-ready image renditions." If "model-ready" means downscaled/re-encoded below the provider's native limits, the harness is destroying the dimension text and fine linework on the plan PNG before the model ever sees it — which would depress build-from-image quality *in every configuration*, bare or full. **Audit items:** log the final pixel dimensions and byte size of every image actually sent; confirm renditions preserve native resolution up to the provider's documented ceiling; compare against sending the same PNG raw via the provider API.

### 1.5 Things that are genuinely neutral
Provider selection, streaming, retries, token telemetry, conversation persistence, artifact hashing, logs — none of these shape model input. Context budgeting and output-token reservation are neutral *mechanisms* but can cause non-neutral *effects* (truncation) — worth logging when reservation actually clips anything.

### How to prove neutrality instead of arguing it
Add a **payload transparency mode**: a debug switch that dumps the exact, final provider request (system string, every message, image dims/bytes, tool schema count — should be zero bare) to a JSONL per request. Then:

1. **Golden-payload regression test:** bare Chat with prompt P and attachment A must produce a payload containing exactly P, A, and the (empty/user) system prompt. Any other token in the payload fails the test. This turns "is it neutral?" from a code-reading exercise into a one-assert regression.
2. **Parity A/B:** same prompt + PNG sent (a) through bare harness and (b) via a raw provider API script. Materially different outputs mean the harness is contributing something the payload dump will reveal.

---

## 2. Assessment of the bare harness and recommendations

### What's good
- The one-request minimal path is the correct architecture; most home-grown harnesses can't claim it.
- All 15 capabilities defaulting to false, and authority (`allow_changes`) separated from mechanism (tools) and from observation (verification), is a genuinely clean model — cleaner than most commercial agent products.
- Durable artifacts with hashing/dedup, retention policies, and exact-evidence addressing is strong infrastructure.
- Token telemetry with cached/uncached/reasoning breakdown is exactly what you need for the ablation work recommended below.

### Recommendations
1. **Payload transparency + golden-payload tests** (above). Highest leverage, small effort.
2. **Empty-by-default system prompt**, with the neutral operational minimum (if any) visible in the UI rather than implicit.
3. **Image fidelity guarantee:** renditions never below native resolution unless the provider ceiling forces it; record final dims in telemetry; surface a UI warning when an image was downscaled ("dimension text may be degraded").
4. **Lazy summarization:** don't summarize until composition actually exceeds budget; keep the most recent N turns verbatim always; make the summarizer prompt domain-free and test it for information retention on a fixture conversation containing numeric dimensions.
5. **Treat mode templates as part of the audited harness.** Publish the four mode instruction strings in the settings UI so "what does Plan mode actually inject?" is answerable without reading source.
6. **Collapse the config space for testing.** Fifteen orthogonal switches with many inert combinations (Detail Crops without Image Planning, Confirmation outside Build, etc.) is a combinatorial testing burden and a foot-gun. Keep the keys for persistence, but present **profiles** — e.g. *Bare*, *Tools* (mcp + microstation + model_tool_access), *Tools+Safety* (+confirmation, advanced verification), *Full* — and drive testing by profile. Retire `enhanced_build` (confirmed no runtime consumer) and resolve `managed_build`'s status one way or the other rather than carrying ambiguous dispatch.

---

## 3. Why results are worse than Claude Code / Copilot with the same MicroStation MCP

Your suspicion is correct, and your own seven-run evidence identifies the mechanisms. The unifying pattern:

> **Claude Code and Copilot are thin at the model interface and put safety at the effect boundary. Your harness is thick in the middle.** Every thick-middle layer either removes information the model needs to converge, or removes turns it needs to converge in. Modern frontier models are RL-trained inside thin harnesses — long agentic loops, raw error text, try/fail/fix — so a thick middle is out-of-distribution for exactly the models you're benchmarking.

Ranked by estimated impact on the house benchmark:

### 3.1 Error opacity kills self-repair (P1.2) — likely the single biggest factor
Runs 2, 5, 6 got only `Unknown exception`. Self-repair — read the traceback, fix the call, retry — is *the* mechanism by which frontier models succeed on unfamiliar APIs. Claude Code pipes raw stderr/tracebacks straight back; your secure executor collapses them. Run 6 shows the contrast inside one session: the probe whose Python error surfaced in `returnValue` was diagnosable; the one that failed at the executor boundary was terminal. Removing the feedback signal removes the capability.

### 3.2 Safety quarantine misfires strip all tools (P1.3)
Read-only probes classified as indeterminate mutations → `tool_count: 0` → runs 5 and 6 built nothing despite having budget left. Claude Code has no equivalent: a failed call returns an error and the loop continues; safety is a per-call approval, not a post-hoc capability amputation. This one bug fully explains two of your seven zero-element runs.

### 3.3 Tool budgets are an order of magnitude too small (P2.2, P1.4)
6 default / 12–20 agentic turns. A build-from-image task honestly needs: discovery, unit probe, smoke test, main build (possibly chunked), structural query, capture, repair loop — 25–50 calls for a model working carefully. Claude Code's loop is effectively unbounded (user-interruptible). Run 6 spent 10 calls just probing. Worse, the model isn't told the budget or the terminal reason (quarantine vs exhaustion were conflated in run 6's own final message), so it can't plan spend.

### 3.4 Static validation is a gate that fails in both directions (P1.1, P0.1)
It passed the run-4 script that crashed the process (false confidence) and its existence encourages "validate then trust" instead of "run small and observe." Verified against MSPy source: `SolidUtil.Convert.BodyToElement(eeh, entity, templateEh, modelRef)` — every Bentley sample passes a *live element* (`solidElement`, `profileElement`, `targetId`) as `templateEh`; run 4 passed a fresh `EditElementHandle()`, which is the access violation. The rule belongs in the validator as a specific contract, but the strategic posture should shift: validation is advisory lint plus a small deny-list of known process-killers, not an execution gate.

### 3.5 The knowledge path is a research treadmill, not a recipe (P1.4)
Prepare/lookup/snippet/pitfall tools invite the model to spend budget researching. Verified against this repo: **Bentley's own samples contain no box-primitive creation example at all** — nothing calls `ISolidPrimitive.CreateDgnBox` or `DgnBoxDetail` in any sample `.py`; the signature exists only in the intellisense stub (`MSPyBentleyGeom.pyi:42310`). So semantic lookup over samples *cannot converge* on the canonical house-building route; models rediscover it by trial every run. The recipe must be authored once, tested, and injected at prepare time. Also verified: run 5's `ModelInfo.GetUorPerMaster()` genuinely doesn't exist, but a static `GetUorPerMaster(modelRef)` binding does exist on the model-ref class (`msdgnmodelref.cpp:641`) — the correct unit idiom is available and should be named in the recipe rather than left for probing.

### 3.6 Intermediate passes are lossy re-encodings
Image Planning (when on) replaces "model looks at the image every turn" with "model reads a one-shot text plan of the image." Claude Code keeps the image in the loop; the model re-inspects it when a wall count or window position is in doubt. A compact scene plan is a lossy bottleneck for a geometry task. Same class of issue as phasing and summarization: every intermediate artifact between the user's input and the acting model discards information.

### 3.7 Ceremony adds failure surface
Receipts, effect planes, nonces, confirmation binding — sound security design, but each is a new place to fail on the critical path (and the evaluator's own four failed capture calls being billed to the candidate, P1.6, shows how harness-side failure contaminates outcome measurement).

**Caveat:** part of the gap may also be image fidelity (§1.4) — check the rendition pipeline before attributing everything to the tool loop.

---

## 4. Strategy: bare base, build up without overcooking

Design principles, then a concrete order of work.

### Principles
1. **The model loop is the backbone; capabilities add tools and context, never control flow.** A capability should mean "the model can now call X" or "the model now sees document Y" — not "the request is now routed through pipeline Z." Retire or quarantine control-flow capabilities (phased execution, managed build, image planning as a forced pre-pass) unless ablation proves them out.
2. **Safety at the effect boundary, not in the loop.** Keep: mode authority, per-call confirmation of exact mutating operations, the small deny-list of known process-killers (BodyToElement-with-empty-template class). Remove: post-failure tool quarantine for read-only work, static validation as a hard pre-execution gate.
3. **Never subtract feedback.** The executor's contract: return everything the runtime produced (stderr, exception type, failing line, native status, fault-log correlation) and *add* context (before/after element counts), never collapse it. "Unknown exception" should be structurally impossible unless the process died.
4. **Budgets generous, visible, and reserved.** Default the agentic loop high (40+), tell the model its remaining allowance, reserve a read-only tail for verification/capture, and always report *why* tools ended (exhausted / quarantined / disabled).
5. **Knowledge as context, not workflow.** One canonical, executable, regression-tested recipe (units → level setup → `DgnBoxDetail`/`CreateDgnBox` → `DraftingElementSchema.ToElement` → `AddToModel` → range query → capture) injected at prepare-time replaces most lookup traffic. Ground it in the intellisense `.pyi` stubs — they are a deterministic, complete API index sitting unused in the MicroStationPython repo.
6. **Let the benchmark layer judge the harness, not just the models.** This is your structural advantage: you already built independent pre/post + visual benchmarking. Point it at capability sets: same model, same prompt, same clean baseline, sweep profiles (Bare+MCP-only → +recipe → +confirmation → +verification → Full). Keep a capability only when it empirically improves task quality or safety. That's the definition of "not overcooking" — measured, not argued.

### Order of work
1. **P0s first** — crash deny-list, stale-run reconciliation, clean-baseline enforcement. Until then every measurement is contaminated (run 4 poisoned run sequencing already).
2. **Fix the evaluator** — standard-view capture (P1.5) and candidate/evaluator actor attribution (P1.6). No trustworthy visual scoring, no trustworthy ablation.
3. **Feedback fidelity + de-quarantine read-only failures** (P1.2, P1.3) — cheapest large quality win.
4. **Budget policy + terminal reasons + verification reserve** (P2.2).
5. **Canonical recipe + `.pyi`-grounded lookup** (P1.4) and level/category organization guidance (P2.3).
6. **Then run the ablation matrix** and let the data decide what else stays.

---

## 5. Creative directions

1. **Harness-ablation benchmarking as a first-class product.** Nobody publishes rigorous data on how harness design changes CAD-agent outcomes. You have independent evaluation infrastructure most labs lack. A grid of {model} × {capability profile} on 3–4 fixed tasks (house-from-image, edit-existing, query/report, cleanup) would be genuinely novel and would settle every "does this switch help?" argument internally.
2. **Closed-loop visual construction.** For build-from-image specifically: after each build stage, capture the viewport and return the capture *to the model alongside the reference PNG* — "compare, list discrepancies, fix." Models are far stronger at visual diffing than at blind dead-reckoning from coordinates. This likely beats any amount of up-front image planning, and it reuses the capture machinery you must fix anyway for P1.5.
3. **Self-growing recipe corpus.** When a session produces a verified working script (structural pass + valid captures), persist it as a named recipe with its outcome evidence. The harness accretes grounded knowledge from successes the way you're currently accreting runtime contracts from failures — both loops automated instead of hand-curated per incident.
4. **Image analysis as a tool, not a pre-pass.** Convert `image_planning`/`detail_crops` into model-callable tools (`inspect_image_region(bbox)` returning native-res crops). The acting model decides when it needs to re-read a dimension string — control stays in the loop, and detail crops stop being inert-unless-planner-asks.
5. **Skills-style knowledge packs.** Small markdown packs (units & UORs, solids, levels/categories, views & capture, item types) loaded on demand via the existing skills facility — cheap, model-agnostic, versionable, and testable independently of code.
6. **Expose the harness itself as an MCP server.** Longer term: wrap your effect boundary (authority, confirmation, receipts, benchmarking) as an MCP server that Claude Code / Copilot / any agent can drive. You stop competing with vendor loops and instead supply the thing they lack — a safe, audited, benchmarked MicroStation effect layer. Your neutrality goal then becomes exact: the loop is theirs, the boundary is yours.
7. **Two-model economics.** Frontier model drives the loop; a cheap model handles summarization, effect classification, and capture-quality checks. Keeps the thick-middle costs off the critical path without deleting the functions.

---

## Appendix: source-verified API facts (from this repository)

| Claim | Verification |
|---|---|
| `SolidUtil.Convert.BodyToElement` signature | `psolidcoreapi.cpp:1318` — `(eeh, entity, templateEh, modelRef)` |
| Samples always pass a live element as `templateEh` | `MSPythonSamples/3DModeling/SolidModification.py` — 15+ call sites, all pass `solidElement`/`profileElement`/`targetId`; none pass a fresh `EditElementHandle()` (run-4 crash shape) |
| `ModelInfo.GetUorPerMaster()` does not exist | `modelinfo.cpp` — only `UorPerStorage` family bound on `ModelInfo` |
| Correct unit accessor exists elsewhere | `msdgnmodelref.cpp:641` — static `GetUorPerMaster(modelRef)` binding |
| No sample demonstrates box-primitive creation | zero matches for `CreateDgnBox`/`DgnBoxDetail`/`CreateBox` in any sample `.py`; signature only in `MSPythonSamples/Intellisense/MSPyBentleyGeom.pyi:42310` |
| Deterministic API index available | `MSPythonSamples/Intellisense/*.pyi` (Bentley, BentleyGeom, DgnPlatform, DgnView, ECObjects, MstnPlatform) |

## Appendix: what needs source-level confirmation (harness code not accessible here)

- Default system prompt content and the four mode instruction templates.
- Summarizer prompt wording and trigger threshold.
- Image rendition target resolution vs provider ceilings.
- Managed Build dispatch reachability (the brief itself flags this as unresolved).
- Exact computed tool budget per Build configuration.

To enable source-level verification in a future session, push the chatbot folder (scripts + a sample of logs/benchmarks; conversations optional) to a branch of this repository, or attach the `.py` files directly.
