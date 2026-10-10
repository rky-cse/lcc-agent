# Library Contents Claim Agent

**Status: M01 implemented and awaiting review. M02 and later modules have not started.**

This project will guide a policyholder through one continuous voice-and-camera sweep of a home library, build a live inventory, and produce an evidence-backed contents claim packet. The brief requires book counting and identification, metric measurements, local book and non-book valuations, room areas, and an honest evaluation against independently collected ground truth.

The first module provides typed packet inputs, evidence checks, exact decimal totals and portable JSON/HTML exports. Live capture, identification, actual measurement and price-source adapters are planned in later modules.

## Read the design

| Document | Purpose |
| --- | --- |
| [Original brief](docs/00-original-brief.md) | Complete supplied requirements, preserved for traceability |
| [Requirements and scope](docs/01-requirements.md) | Pass bars, deliverables, constraints and ownership |
| [Architecture](docs/02-architecture.md) | Pipeline, boundaries, runtime, state and failure handling |
| [Contracts and packet](docs/03-contracts.md) | Stage outputs, required packet fields, provenance and totals |
| [Capture and measurement](docs/04-capture-measurement.md) | One-sweep interaction, scale options, geometry and uncertainty |
| [Identification and valuation](docs/05-identification-valuation.md) | Detection, physical-copy matching, catalogue evidence and price sources |
| [Reference audit](docs/06-reference-audit.md) | Inspected code, reuse decisions and actual execution results |
| [Modular implementation plan](docs/07-implementation-plan.md) | Small work packages with tests, smoke checks and review stops |
| [Evaluation and ground truth](docs/08-evaluation.md) | Sampling, formulas, full denominators and result templates |
| [Operation and delivery](docs/09-operations-delivery.md) | Setup plan, cost/latency, evidence handling and submission checklist |
| [Decisions and risks](docs/10-decisions-risks.md) | Questions awaiting answers, proposed decisions and feasibility risks |
| [One-page architecture note](docs/11-architecture-note.md) | Concise proposed design for the eventual submission |
| [Failure log template](docs/12-failure-log.md) | Actual failures to record after implementation and real capture |
| [M00 preflight results](docs/13-m00-preflight.md) | Isolated reference environment, 55 Python tests, startup/endpoint smoke and remaining live prerequisites |
| [M01 review record](docs/14-m01-review.md) | Implemented boundaries, tests, synthetic smoke and review artifacts |

## Current verification

Reference inspected at `E:\awesome_llm_apps\awesome-llm-apps\voice_ai_agents\insurance_claim_live_agent_team`, repository revision `4bf51ab704fb2c5b3803cd5191b30d7dcdb51dc2`. On 10 October 2026, its existing JavaScript tests passed: 18 client regressions and 7 avatar-player tests. They use mocks and do not validate real camera, microphone, model access or measurement accuracy.

The user confirmed they tested the reference and instructed us to proceed without further reference testing. That baseline is accepted. Historical checks are recorded in M00; target phone/camera behavior will be verified in the capture module.

M01 verification: 29 unit/contract/export tests pass. The synthetic CLI produces a partial packet with saved evidence and an HTML report from the same serialized values. No real capture or price quote is claimed by that fixture.

## Run M01

Requires Python 3.12+ and the pinned Pydantic dependency. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B -m library_claim --country IN --currency INR --currency-decimal-places 2 --exclusion-basis missing_any_component --shelf-run-basis sum_spine_thickness --output runs/my-m01-review
```

IN/INR are explicit synthetic example inputs, not application defaults. Choose a fresh output directory each time. Open its `report.html`; JSON, frames and quotes remain usable after temporary fixture cleanup. The current workspace checks used `.local/reference-env/Scripts/python.exe`; only Pydantic is required by M01. No API key is needed for this module.

## Review workflow

The user controls implementation. M01 was authorized by the instruction to begin implementation one part at a time. Work stops after this module's tests and smoke for review. Fixes or progression to M02a require the user's next instruction.

Start review with [the open decisions](docs/10-decisions-risks.md) and [the module plan](docs/07-implementation-plan.md). The largest unresolved technical choice is how the capture device supplies trustworthy metric scale and room geometry.
