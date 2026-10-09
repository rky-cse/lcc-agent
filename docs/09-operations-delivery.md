# Operation, observability and delivery plan

Status: future operational specification. No environment, app, credentials, deployment or submission has been created.

## Setup and dependency policy

Target a documented local development/demo setup that a stranger can complete in under 15 minutes. The reference asks for Python 3.12; this host currently exposes Python 3.13.1 without its required packages. M00 must pick and test a compatible runtime. Record OS/runtime/dependency versions, then lock selected dependencies rather than carrying unrestricted upstream minimum versions into a supposedly reproducible setup.

Proposed runtime: Python, FastAPI, typed schemas, an available image/geometry library, selected provider SDK, local transactional state and plain browser JavaScript. Add OCR/pretrained detection dependencies only after feasibility and need are demonstrated. No training from scratch. Avoid blanket ADK/avatar/cloud dependencies when their features are omitted. Disclose every model/provider/library and the purpose it serves.

Future `.env.example` contains placeholders only. Suggested settings: live/vision/OCR provider model IDs, provider key placeholders, source adapter keys where needed, default locale only if explicitly chosen, source rate/freshness policy, data directory, queue limits, calibration mode, appraisal thresholds, stage/end deadline and fees/condition policy. Validate configuration at startup and show actionable missing capability messages. Never commit `.env`, model keys, provider session tokens or real private capture by accident.

A phone demo needs trusted camera/microphone access to the local backend. Select a minimal secure development access method on the actual device during M00; document exact steps and limitations. Also test HTTP and WebSocket host/client/origin handling: the reference's loopback-only guard rejects a direct PC LAN connection. Deliberately configure/adapt that guard for the authorized development route rather than removing access checks broadly. This does not justify building authentication/deployment infrastructure. Keep API keys server-side and session ownership lightweight. Browser permission prompts remain required by the platform.

## Evidence layout proposal

`runs/<sweep_id>/` contains an immutable configuration snapshot, append-only events/stage results, `frames/`, derived `crops/`, calibration/pose/depth evidence where available, source quote records, packet revisions, HTML report and cost/latency ledger. A manifest maps IDs to relative paths/hashes/timestamps. Raw frames are never replaced by enhanced or generated images.

Use safe sweep-generated IDs and resolved relative paths; do not trust model/client paths. Validate decoded file format, byte/pixel limits and hashes. Keep source HTML/scripts inert in report output; escape model, OCR, claimant and source text. Price retrieval accepts only configured source adapters; fetch URLs cannot target arbitrary local services. These are small data-boundary protections, not a compliance or security product.

Privacy requirements come from the brief: capture no people/private documents and get permission for non-owned spaces. Detecting personal content reliably is not assumed; arrange the room and allow claimant stop/exclusion. Local frame retention and which providers receive camera/audio/crops must be explained before real capture. Retention/deletion defaults are unresolved; preserve referenced evidence until user-approved export/retention policy is set. Remove credentials from exported debug logs. Do not share or upload artifacts externally without instruction.

## Observability

| Record | Required fields/purpose |
| --- | --- |
| Stage timing | Sweep/job/stage IDs, enqueue/start/end monotonic times, terminal status, input revision and evidence refs |
| Usage | Provider/model/version, tokens or media seconds/images, requests, retries, returned usage and source of accounting |
| Price-source activity | Source/locale/query, fetch count, latency, status/rate limits and cache hit/freshness |
| Capture health | Actual media resolution, frame rate/bytes, upload acknowledgement latency, dropped preview count, evidence gaps |
| Geometry quality | Calibration tolerance, fit residual, tracking failures, boundary completeness and scale version |
| Cost ledger | Usage units × dated configured unit rate, fixed source costs and actually incurred retries |

Report actual charged cost when available; label estimates if provider usage or bill data is incomplete. Do not invent per-sweep cost from intuition. Keep rate version/date and accounting currency; user spend cap is unresolved. Add a configurable cap after approval and stop scheduling optional retries when it would be exceeded, with visible unavailable results.

Stage elapsed sums are not the end-to-end duration when jobs run concurrently. Report queue delay, processing latency, critical path, sweep time, end-to-packet time, and sample counts. In a single demo there is one observed latency, not a meaningful P95; report percentiles only after enough repeated runs and disclose N.

## Live-session continuity

If Gemini Live is chosen, configure and test context compression/resumption for a sweep exceeding the documented default audio/video session duration. Persist authoritative state outside model context and provider connections. [Google session management](https://ai.google.dev/gemini-api/docs/live-api/session-management). Selected provider configuration, interruption behavior and account quotas need actual preflight; official documentation is not proof the account has access.

Set bounded retries with timeouts inside the overall <300-second end-to-packet budget. Stop background scheduling before the deadline, then export a contract-valid partial packet with coverage/failure reasons when necessary. A file containing broken references is not a successful packet. Geometry/source failure may preserve integrity while still failing accuracy/coverage requirements; state both.

## Demo and time budgets

Two separate limits apply: target sweep <180 seconds, and packet <300 seconds after sweep end. The demo must also fit ≤360 seconds unedited. Therefore `greeting + actual_sweep + end_to_packet + summary ≤360`; merely meeting the two separate maxima could produce an eight-minute run and fail the demo limit. During integration choose a measured tighter target for demo processing, usually well under three minutes if the sweep itself approaches three minutes. Do not edit/speed up/stitch footage to satisfy the limit.

Record a single actual continuous pass with the agent audible, inventory arriving during capture, explicit sweep end and the final packet opening. Save the demo's exact sweep ID and packet revision. Offline replay may diagnose stages but cannot replace the live-demo evidence. The second-country demonstration can be a separate artifact using the same ten physical IDs.

## Submission checklist

- Private repo with reproducible README, `.env.example`, pinned/locked dependencies, model/library/source disclosure and upstream reuse notices.
- Successful clean setup rehearsal timed under 15 minutes, with real device/provider caveats stated.
- One unedited demo ≤6 minutes containing live voice, continuous sweep, live inventory and packet.
- Demo's `claim_packet.json`, readable report and saved referenced frames/manifest.
- Ground-truth/results sheet covering every required denominator/sample and every pass bar, including failures/unavailable results.
- Final one-page architecture note naming actual model roles, metric path and price sources.
- Final one-page failure log containing three observed worst errors, root causes, measured fix, actual/estimated cost and stage latency.
- Same ten books repriced for the second locale, with source/date/currency/FX disclosures.

Repository sharing, video upload and email submission are later user-authorized external actions. This documentation step neither creates a private GitHub repository nor claims those deliverables exist.
