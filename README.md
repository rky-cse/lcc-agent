# Library Contents Claim Agent

**Status: design and planning only. No application implementation has been authorized or added.**

This project will guide a policyholder through one continuous voice-and-camera sweep of a home library, build a live inventory, and produce an evidence-backed contents claim packet. The brief requires book counting and identification, metric measurements, local book and non-book valuations, room areas, and an honest evaluation against independently collected ground truth.

The current deliverable is the documentation below. Recommendations are proposals for review; unresolved choices are explicit. A feature description is not a claim that it already works.

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

## Current verification

Reference inspected at `E:\awesome_llm_apps\awesome-llm-apps\voice_ai_agents\insurance_claim_live_agent_team`, repository revision `4bf51ab704fb2c5b3803cd5191b30d7dcdb51dc2`. On 10 October 2026, its existing JavaScript tests passed: 18 client regressions and 7 avatar-player tests. They use mocks and do not validate real camera, microphone, model access or measurement accuracy.

Reference backend startup was attempted and failed before startup: `C:\Python313\python.exe: No module named uvicorn`. The current Python environment also lacks FastAPI, Pydantic, Google SDK packages and HTTPX. The reference's supplied `venv/pyvenv.cfg` points to Linux Python 3.12.3 and cannot be treated as a Windows environment. No dependencies were installed and no provider requests were sent. A successful reference live run remains a mandatory preflight before new application code, as required by the brief.

Documentation validation passed: 14 Markdown files, 18 local links, all 59 distinct required packet keys and 12 module acceptance cards checked. The original brief body is preserved, including its original whitespace. Independent read-only reviews checked reference reuse, measurement feasibility and pricing/contracts; identified consistency gaps were corrected. The workspace contains documentation only.

## Review workflow

The user controls implementation. After documentation review and answers to the blocking questions, the user must explicitly authorize a named module. Work will then implement only that module, run its relevant checks, show its concrete result and stop for review. Fixes and progression to another module require the user's next instruction. Documentation approval alone does not authorize implementation.

Start review with [the open decisions](docs/10-decisions-risks.md) and [the module plan](docs/07-implementation-plan.md). The largest unresolved technical choice is how the capture device supplies trustworthy metric scale and room geometry.
