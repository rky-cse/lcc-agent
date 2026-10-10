# M00 — Reference and prerequisites

Current disposition: user-tested reference baseline accepted. The user instructed us to stop reference tests and start implementation one part at a time. M01 is authorized; future target-device/source checks belong to M02/M03/M06/M07. The original verification record below is historical and superseded where noted here.

Before that instruction, a provider-only connection smoke completed: generated final transcript "Connection test passed", 82,560 bytes of PCM (1.72 seconds), 4.32-second round trip. Local diagnostics are ignored under `.local/`. This checked provider transport/audio, not a real microphone/camera sweep. The latest user confirms the existing Gemini key is free tier, superseding the earlier replacement request. M01 makes no provider calls. No further reference tests are required for M01.

## Scope and changes

Run and assess the existing reference before new application code. Create an isolated local environment, test compatibility and the reference regressions, then smoke-check startup/endpoints. A real voice/camera/provider run and device/source preflight require the user's pending answers. The reference source and credentials remain unchanged.

Created `.local/reference-env/` with the installed Windows Python 3.13.1. This is a compatibility experiment: the reference README specifies Python 3.12. Added `.gitignore` to exclude local environments, credentials and real capture data. No target application code was added.

The initial package download failed because sandbox network access was blocked (WinError 10013). The same dependency installation was then requested through the required escalation mechanism. Installation uses the reference's `requirements.txt` plus HTTPX for its existing TestClient tests. Dependency installation is not a provider/model call.

## Verification record

| Check | Current result |
| --- | --- |
| Isolated Windows environment creation | Passed |
| Reference dependency installation | Passed in isolated Python 3.13.1 environment |
| Installed dependency consistency | Passed: pip check reports no broken requirements |
| Reference Python regressions | Passed: 55 tests, 0.542 seconds; provider/device behavior mocked |
| Backend startup | Passed: Uvicorn listening on 127.0.0.1:4177 |
| HTTP assets and health | Passed: root, app.js, styles.css and health return 200 |
| Session/packet smoke | Passed: own session create/read/delete; valid empty ZIP containing claim.md and evidence.json |
| Negative boundary smoke | Passed: mutation without Origin rejected; unknown WebSocket session rejected before provider connection |
| Positive provider WebSocket / actual voice and video | Not tested; the negative handshake is not proof of a live provider session |
| Real microphone/camera, interruption and paid model access | Pending user/device/provider information |
| Primary/second-country physical price source smoke | Pending locale/provider information |
| Independent ground truth / actual room | User will arrange books; mandatory room/shelf/item counts and measured truth await actual setup |

Installed direct/boundary versions: google-adk 2.11.0, google-genai 2.29.0, FastAPI 0.141.1, Uvicorn 0.54.0, Pydantic 2.14.0, HTTPX 0.28.1 and Starlette 1.7.0. Complete installed versions are saved locally in ignored `.local/reference-environment.freeze.txt`. These are reference-baseline dependencies, not the chosen dependency set for the new application.

The test suite emitted a Starlette deprecation warning for its HTTPX TestClient integration; all tests passed. This is recorded rather than changing reference code or installing an unnecessary replacement now. Python 3.13 compatibility is established for the exercised tests/startup, not every live SDK/device feature.

The health endpoint reports an API key configured and the reference's live model as `gemini-3.8-live`; key validity, quota and paid model access are untested. No key was displayed or copied. This preflight made zero model requests.

The reference was verified at [localhost:4177](http://127.0.0.1:4177/). Its preflight process is now stopped while the user replaces the old key. It is not an installed background service. To restart from the reference directory, use the isolated interpreter with `-B -m uvicorn live_demo.server:app --host 127.0.0.1 --port 4177`. No source files in the reference were modified.

## Real-device smoke still required

On the intended device/development route, verify microphone/camera permission, audible response, interruption while speaking, evidence capture, packet download and reconnect. Record provider errors without exposing keys. A phone LAN URL will need the secure-context and reference-loopback restrictions resolved; the desktop localhost page is not proof of phone compatibility. Confirm locale/source access before physical new/used quote checks. The empty smoke ZIP is reference output, not the assignment's claim_packet.json.

## Pending information

User confirmed Android phone or laptop browser, no LiDAR, a reference object allowed, free-tier Gemini/Groq, dynamic country/currency prompts, and that books will be arranged. Before pausing for key replacement, browser inspection confirmed the rendered reference page exposes voice/camera controls, transcript, notebook and packet controls; its initial seeded greeting is not evidence of a provider response.

User will replace the reference's `.env` key with a free-tier Gemini key. The old process was stopped through its exact preflight execution session, and the local endpoint was verified offline, so it cannot initiate calls with the old key. The `.env` file was opened in the local editor for the user without displaying its contents in chat. After the user reports replacement ready, restart the process and test the free-tier connection.

Other remaining live-preflight details: actual first-test device/browser and reference object's verified dimensions. Actual locale inputs are supplied when a sweep/source test starts; the agent must ask them instead of hardcoding a country. Room ground truth and deadline remain pending when available. Do not paste keys into chat. No paid provider requests or source-policy selections will proceed by assuming missing facts.

Historical gate, now superseded by the user's reference-test acceptance: the original checklist requested live/device/source verification before M01. Actual target phone, geometry and source checks remain required in their respective modules; reference retesting no longer blocks implementation.
