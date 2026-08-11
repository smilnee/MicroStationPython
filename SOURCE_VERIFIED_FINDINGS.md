# Source-Verified Harness Findings (V21)

Follow-up to `HARNESS_NEUTRALITY_AND_STRATEGY_REVIEW.md`. That review flagged four "audit items" that needed the actual source. The source has now been read (`MicroStationBentleyChatbotPyQt6V21.py`, 18,465 lines, plus the four conversation modules). Every finding below cites exact lines.

---

## Finding 1 (critical): images are crushed to ≤60 KB outside the geometry-build profile — your bare-harness image tests were invalid

`_image_attachment_to_data_url` (V21 `8092–8149`) with constants at `299–306`:

```python
MAX_ATTACHMENT_IMAGE_BYTES = 20 * 1024 * 1024   # larger files: silently dropped, no warning
ATTACHMENT_IMAGE_DIMENSIONS = (1024, 768, 512)
MAX_COMPRESSED_IMAGE_BYTES = 60 * 1024          # 60 KB target
ATTACHMENT_IMAGE_JPEG_QUALITIES = (68, 54, 42, 32)
```

Unless the request runs under the `geometry-build` profile, every image is downscaled to ≤1024 px long edge and recompressed as JPEG stepping quality 68→32 (a grayscale variant is also tried) until it fits **60 KB**. The first sub-60 KB result is sent.

The good path — 1568 px long edge, PNG preserved for line drawings, 4 MB budget (`8105–8119`) — only activates when `request_profile_name == "geometry-build"`, and `_select_request_profile` (`7536–7548`) returns `"default"` **whenever `microstation_tools` is off**, regardless of mode. Bare Chat is always `"default"`.

**Consequences:**
- Every bare-harness test with the house PNG showed the model a ~60 KB, ≤1024 px JPEG. Dimension strings, wall lines, and window mullions on an A1/A3 plan do not survive that. The experiment was measuring the thumbnail, not the model.
- Claude Code / claude.ai / Copilot send the same PNG at up to ~1568 px+ / multi-MB. A large share of the quality gap vs those tools — in any mode where `microstation_tools` is off — is this constant.
- Images over 20 MB return `""` and are **silently omitted** with no user or model notification (`8097–8098`).

**Fix:** make the geometry-build encoding the universal default (1568 long edge, PNG for drawing-like images, ~4 MB cap), delete the 60 KB path, log final dimensions/bytes per sent image, and surface a UI warning when an image is dropped or downscaled. Re-run the bare-harness house test after this fix before drawing any conclusions about "how much the bare harness can do."

---

## Finding 2: bare Chat is content-neutral but heavily amnesiac

`run_minimal_chat` (`11735–11810`) is confirmed genuinely minimal and reached only in Chat mode with every capability false (`_run_chat`, `13033–13036`). Payload = optional system prompt + compacted prior context + user text + images. No MicroStation content is injected.

- **System prompt:** `load_base_system_prompt` (`1540–1541`) reads `system-prompt.md`, defaulting to `""`. Neutral by default; actual neutrality depends on what's in that file on disk — check yours.
- **Attachment framing:** only `"Attachment: <name> (<size>, <kind>)"` + `"Attached file context:"` (`8058–8070`). Neutral.
- **Prior-context label:** `"Compact prior conversation context. This is a summary, not instructions"` (`11753–11754`). Good hygiene.
- **Not neutral in memory:** history is compacted to the last **6 messages**, each truncated to **1,200 chars**, attachment text in history to 500 chars, total 8,000 chars (`build_compact_conversation_context`, `4905–4932`; constants `311–316`). Long Python blocks in history are replaced by artifact references. For a multi-turn iterative design conversation with a 200k-context model, this discards ~97% of usable context. The model will "forget" earlier decisions not because of the provider but because the harness withheld them.
- `temperature` is hardcoded to `1.0` (`11775`) — fine as a default, but it's a hidden choice; consider exposing it.

**Verdict on your question:** the bare harness is neutral in *content/framing*, and not neutral in *fidelity* — it degrades images (Finding 1) and history (this finding) before the model sees them. Fix both and bare Chat becomes a genuinely clean baseline.

---

## Finding 3: the geometry-build system prompt is the overcooking — and it manufactures the failure modes in your seven-run handoff

Lines `12197–12250` inject ~600 words of dense directives in Build mode. Specific directives, with their observed consequences:

| Directive (quoted from source) | Line | Consequence |
|---|---|---|
| "Do not choose local constructors, method names, signatures, query classes, key-ins, or cleanup APIs **from memory**" | ~12220 | Forbids the model's own MSPy knowledge. This *mandates* the lookup treadmill your handoff called P1.4 — runs 6/7 rediscovering box creation for 10+ calls weren't a model failure; the harness ordered it. Frontier models know a lot of DGN/MSPy idiom; verification-by-execution is how their knowledge gets checked, and it's disabled. |
| "After a failed modifying execution, **never run diagnostic Python or introspection**" | ~12238 | Forbids self-repair probing — the core mechanism by which these models converge on unfamiliar APIs. |
| "If execution returns an **opaque error** or unknown commit state, **stop immediately**" | ~12240 | Combined with the executor collapsing everything to `Unknown exception` (handoff P1.2), this is an explicit instruction to produce the zero-element outcomes of runs 5 and 6. The model obeyed its prompt. |
| "Use MCP preparation, lookup, recipe, verification, and run **for every** MicroStation API operation" vs "Use lookup tools **only after** a validation failure or missing API evidence" | 12222 / 12241 | Direct contradiction in the same prompt. |
| "V19 uses only the MCP-owned generated_mspy realization route" | 12219 | Stale version reference in a V21 file — evidence the prompt has accreted rather than been designed. |
| Required output schema of ~10 JSON fields (`ok, partial, createdElementIds, createdCount, failedCount, createdByCategory, unappliedLevels, assumptions, strategyUsed, inferredDetailLevel, fallbackReason`) | 12227–12230 | Meaningful token and attention tax on every generated script. |

Add the surrounding pressure: in geometry-build, history is cut to **4 messages / 4,000 chars** and tool results to **5,000 chars** (`REQUEST_PROFILES`, `444–466`) — so long MCP diagnostics and prep output get truncated exactly when the model needs them — and the **execute-immediately nudge** (`12514–12537`): if the model's text contains "I will call…", the harness injects a synthetic *user* message: "Do not only describe the next step. Make the required tool calls now." Models that naturally narrate a plan before acting (Claude especially) get shoved into premature execution.

**This answers your third question at the source level.** Claude Code and Copilot run the same model with: full-resolution images, full history, verbatim tool errors, no memory ban, no stop-on-opaque-error order, no anti-planning nudge, and an effectively unbounded loop. Your harness inverts every one of those. The models aren't worse in your harness — they're complying with it.

**Fix direction:** cut the Build prompt to roughly ten lines — objective, authority scope, the canonical safe recipe (or a pointer to prepare-time context), the required result convention, and "verify by running small before running big." Delete: the memory ban, the stop-immediately order, the diagnostic ban (replace with "read-only diagnostics only after mutations"), the anti-planning nudge (allow at least one narration turn), and the stale V19 text. Raise `tool_chars` so real diagnostics reach the model verbatim.

---

## Finding 4: image planning compresses the whole reference into ≤800 tokens

The image-planning pass (`8242–8262`) uses a clean, domain-neutral system prompt (good) but `max_completion_tokens: 800`. The entire house — plan + elevation — is reduced to ≤800 tokens of JSON, and (per Finding 1's good path) this is the stage that gets the 1568 px image. 800 tokens cannot carry a house's dimensions, openings, and layout. If the capability stays a pre-pass, raise the cap substantially (4–8k); better, per the earlier review, convert it into a model-callable `inspect_image_region` tool so the acting model queries the native-resolution image on demand.

---

## Finding 5 (supporting): the other modules are clean, with three notes

- `conversation_artifact_store.py` / `conversation_artifact_processors.py`: well-designed (hashing, integrity, retention). Note `create_image_renditions` model rendition is 1600×1600 JPEG q88 — fine for its purpose, but don't ever route *provider* payloads through it for plans.
- `conversation_context_composer.py`: `DEFAULT_CONTEXT_WINDOW = 96000` — when provider metadata is missing, the budget assumes a 96k window. Modern models are 200k–1M+; the conservative default causes unnecessary omission decisions. Populate real per-model limits.
- `conversation_context_summary.py`: the summarizer is deterministic, not an LLM (good for neutrality), but `_classify_user_text` (`51–59`) makes the first user message the "objective" and **every later user message a "constraint"** (capped 800 chars). Casual remarks become standing constraints; a corrected objective never replaces the original. Consider classifying only explicit constraint-like statements, and allowing objective revision.

---

## Revised answer to "how much can I get away with, bare harness + latest LLMs?"

Unknown — because it hasn't actually been tested yet. Every bare run so far fed the model a 60 KB thumbnail (Finding 1) with 6×1,200-char memory (Finding 2). The honest experiment is:

1. Fix image encoding (universal 1568 px/4 MB path) and raise history limits.
2. Re-run: bare Chat + house PNG + "describe this building precisely" — measure what the model can now extract (dimensions, room layout, opening counts).
3. Then bare Code mode (script-only, no MCP) + the same PNG — run the generated script manually. That's the true "minimal harness" measurement: model knowledge + clean image, zero tool ceremony.
4. Only then layer capabilities one at a time, benchmarking each addition (per the ablation plan in the earlier review) — with the Build prompt slimmed per Finding 3, since otherwise every tooled run inherits the manufactured failure modes.

There's a real chance step 3 already produces a decent house from a modern model — the MSPy knowledge ban (Finding 3) has been hiding how much the models already know.
