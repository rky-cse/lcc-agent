# M06b — Live voice transport and session recovery

Implemented for the latest “next”: an optional Gemini Live adapter, bounded WebSocket transport, microphone capture, PCM playback, interruption clearing, explicit reconnect and browser review of spoken-answer proposals. It consumes M06a's authoritative guided state. Recognition scheduling, geometric calibration, inventory correction execution and finalization remain separate modules.

## Interaction and review boundary

Open `/voice` and create a guided session or enter its existing ID. The initial question asks country/currency with no defaults. Connect voice explicitly; microphone capture stays off until **Start microphone**. Typed answers can exercise the same conversation without granting microphone access. The agent uses `guidance_state` to inspect authoritative state and `propose_guidance` to prepare a strictly typed claimant answer. A proposal does not change guidance or inventory. Its literal statement, selected codes, dimensions and other fields appear for **Confirm this answer** or **Dismiss proposal**.

Confirmation submits the existing revision-guarded GuidanceCommand through M06a's HTTP endpoint. Guidance validates the phase, target and current revisions. Invalid/stale proposals remain unaccepted and require clarification. Exact command retry is idempotent. Dismissals persist in the voice journal; confirmation is resolved from the guidance audit rather than a guessed model acknowledgment. Multiple proposals remain in the journal for sequential review. Cancellation disables confirmation in the current browser view. Signed/first-edition/ownership assertions never directly authenticate or update books.

Reference answers require actual measurements/tolerances and provenance. A skip leaves dimensions unknown. `metric_ready` stays false. Once setup is ready, **Open camera capture for this session** supplies the existing capture page with the guidance ID and authoritative locale. Camera permission is still explicit. Return to voice and **Bind started capture** to verify the lifecycle and locale. The capture page refuses switching away from a different unfinished saved capture. An existing bound session can reopen its saved capture.

**Send saved-frame preview** verifies an original in the same active bound sweep, resizes a separate RGB JPEG to at most 640 pixels and sends only that conversational preview. The immutable original remains unchanged. This is a manually selected preview, not automatic video scheduling, OCR or metric evidence. Sending a preview does not acknowledge a requested evidence analysis as completed. Books remain in place; invisible ISBNs remain unknown.

**Disconnect voice** never closes a capture. **Stop microphone** sends the provider audio-stream-end signal; **Stop playback** clears local queued audio but does not itself cancel provider generation. Actual speech/VAD interruption clears all queued playback and suppresses cancelled model audio. Hiding the page stops microphone capture and clears playback; reconnect is explicit. No microphone or camera permissions were granted during the browser fixture smoke.

## Transport, limits and recovery

`library_claim/live_voice.py` separates optional SDK transport from VoiceHub and VoiceJournal. `/ws/voice/{session_id}` enforces exact configured Host and Origin independently of HTTP middleware. Voice is disabled unless the server is started with `--voice --free-tier-confirmed`. The only reviewed model is `gemini-3.8-live`; there is no paid-model fallback, automatic retry, browser key, avatar or policy workflow. A key's billing tier cannot be determined by this application; the CLI flag records the user's explicit free-tier configuration assertion.

The browser uses AudioWorklet blocks of approximately 100 ms, reference-derived PCM resampling and explicit little-endian PCM16 at 16 kHz. Output is PCM16 at 24 kHz. Scheduled playback is bounded to five seconds; transport backlog stops microphone streaming instead of accumulating recordings. Generation and server-epoch guards reject late output from old connections. Microphone request generations release late permission results after stop/disconnect. Raw microphone audio and provider audio are not saved locally.

WebSocket control envelopes allow only audio, text, saved-frame ID, refresh, audio-end and close. Input limit is 48,000 UTF-8 bytes; each PCM chunk is at most 16,000 bytes/0.5 seconds. Rates are at most 20 audio messages/second, one preview/second and 30 messages/minute for each other type. Text is bounded to 2,000 characters. SDK setup has a 25-second timeout, socket sends 10 seconds, and target connection lifetime 20 minutes. One live connection is permitted globally per server instance; deployment remains one worker. Original verification/SQLite/proposal work runs outside the async transport loop. No recognition job is launched here.

Context-window compression and provider resumption are configured. Resumable handles remain only in server memory, expire locally before two hours, and never enter the browser, journal or exports. A provider go-away asks the browser to reconnect explicitly. A rejected/failed connection clears the handle; a later explicit reconnect starts fresh. Durable guidance, the last bounded unverified conversation events and unfinished proposals rehydrate the model on every connection. Server restart restores this local context but cannot restore the in-memory provider handle. It does not guarantee replay of every media packet lost during a disconnect.

The SQLite voice journal stores server epoch, up to 500 transcript/tool/lifecycle events and up to 20 proposals per guided session. Unfinished transcript chunks survive disconnect but are unverified conversation, not field evidence. The proposal cap is a prototype session limit; a production retention/compaction policy is not implemented. `/api/guidance/{id}/voice` exposes this journal; POST `/api/guidance/{id}/voice/dismiss` persists an explicit dismissal. Existing HTTP Origin/body bounds apply. SDK exception text is never forwarded or logged because it may contain credentials or private resumption handles.

Provider formats and lifecycle were checked against the official [Live capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities), [session-management guide](https://ai.google.dev/gemini-api/docs/live-api/session-management) and [free-tier pricing](https://ai.google.dev/gemini-api/docs/pricing) on 10 October 2026. Compression/resumption configuration supports the planned longer conversation; it is not an observed three-minute device test.

## Run and review

Install the optional voice dependency in your chosen environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
.\.venv\Scripts\python.exe -B -m library_claim.server --store runs/my-live-library --port 4186 --voice --free-tier-confirmed --key-file E:\awesome_llm_apps\awesome-llm-apps\voice_ai_agents\insurance_claim_live_agent_team\.env
```

Open `http://127.0.0.1:4186/voice`. The locally confirmed reference key file is read at startup; no reference application is started or tested and no credentials are copied. Environment variables `GEMINI_API_KEY`/`GOOGLE_API_KEY` can replace `--key-file`. The current isolated environment already has `google-genai==2.29.0`; no dependency installation was needed for this module. Normal capture without `--voice` remains key-free. Health reports voice enablement.

```powershell
.\.venv\Scripts\python.exe -B scripts/smoke_voice.py --output runs/my-voice-fixture
.\.venv\Scripts\python.exe -B scripts/smoke_voice.py --output runs/my-voice-provider --gemini --free-tier-confirmed --key-file E:\awesome_llm_apps\awesome-llm-apps\voice_ai_agents\insurance_claim_live_agent_team\.env
```

Choose fresh output directories. The fixture smoke uses actual HTTP/WebSocket and separate server processes but a controlled provider. The Gemini command makes bounded real provider connections and sends explicit synthetic content; it is not an actual microphone or real-library test. Logs/summary omit keys, private handles and base64 audio; `events.json` preserves reviewed proposals and state transitions.

## Verification and limitations

23 new Python voice tests and five new Node tests cover Host/Origin, default disablement, exclusive connection, locale-first restoration, PCM bounds, interruption, tool rejection/proposals, explicit confirmation, decimal-reference retries, cancellation/dismissal, resumption secrecy/epochs, journal persistence, redacted failures, playback clearing and old-generation suppression. All 21 Node tests passed. Final full Python regression: 300 tests passed. The existing Starlette/HTTPX deprecation warning remains. An earlier regression run exposed a Windows temporary-file cleanup race when the test cancelled a socket before the server finished its journal write; the test now waits for the actual close handshake. No failure was suppressed by ignoring filesystem errors.

Actual fixture HTTP/WebSocket/restart smoke passed in `runs/m06b-fixture-integrity`: initial locale unknown, model proposal unapplied, explicit GB/GBP confirmation, declared reference skip, started/bound synthetic capture, original preview/hash preservation, interruption, reconnect with provider handle, fresh connection after server restart, increasing epochs and durable proposal context. Voice disconnect left capture active; inventory revision stayed zero and metric readiness false.

The first restricted Gemini connection failed. The permission-backed target smoke then passed in `runs/m06b-live-approved`: 36 returned audio chunks, locale proposal/explicit confirmation, saved original preview, short reconnect using provider resumption and unchanged inventory. It also exercised a synthetic silent PCM input plus audio-stream-end through the SDK. This does not verify speech transcription, actual microphone barge-in, audible device playback quality or a three-minute session. No further reference-app tests were run.

Actual in-app browser fixture smoke created session `95de1b71de5141e39c3b514414e65905`, connected with microphone off, displayed the GB/GBP proposal while still asking locale, confirmed it, advanced to the measured-reference question and disconnected without discarding guidance. Evidence: `runs/m06b-browser-review/voice-confirmed.png`. Browser source text is rendered literally; no model HTML is injected. Actual camera/microphone permission, Android/HTTPS route, automatic preview scheduling, provider go-away timing, quota exhaustion and real shelf accuracy remain unverified.

Reuse: the reference's media envelopes, PCM conversion/playback and interruption-first output handling were adapted into target-native modules. Target capture originals, M06a questions/commands, revisions and storage were reused. Discarded: reference insurance narrative/policy/ADK graph, avatar/sketch, RAM-only intake and model-authored inventory. The next separately authorized module is M06c orchestration: recognition scheduling and audited correction execution/acknowledgment, split further if review scope requires it. Real-device/three-minute voice acceptance remains an open M06b validation item.
