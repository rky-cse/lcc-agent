# Library Contents Claim Agent

Use this local web app to capture a bookshelf, detect visible spines, review book identity, and prepare an evidence-backed contents claim.

The app is designed to be honest about uncertainty: a detected spine is not automatically an accepted book, and a visible title is not automatically a confirmed edition or price.

## Quick start

You need Python 3.12+ and a Gemini API key for live recognition. Node is only needed for browser tests.

Create a local `.env` file from the example and add one key:

```bash
cp .env.example .env
# Edit .env and set either GEMINI_API_KEY or GOOGLE_API_KEY.
```

Create the environment and install dependencies.

```bash
python -m venv .venv
source .venv/bin/activate            # Linux / WSL
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements-voice.txt
```

Start the app:

```bash
python -B -m library_claim.server \
  --store runs/my-library \
  --port 4186 \
  --voice \
  --recognition \
  --free-tier-confirmed \
  --key-file .env
```

Open [http://127.0.0.1:4186/](http://127.0.0.1:4186/).

`--voice` is optional. `--recognition --free-tier-confirmed` enables saved-image detection and spine reading. Your key stays on the local server and is never sent to the browser.

## Normal workflow

1. In the voice panel, enter country, currency, and the measured reference-object details.
2. Start and bind camera capture.
3. On **Automatic shelf recognition**, set the shelf, region, limits, and budget; tick consent; then select **Start this shelf plan**.
4. Move slowly across the shelf. End the sweep only after the recognition plan has started.
5. Open **Books and review**. Use the action buttons to resolve each detected spine as a new physical copy, an existing copy, or unresolved.
6. For accepted physical books, open **Book identification** and review the literal spine text and catalogue match.
7. Open **Book prices** after a book is physically accepted and identified. Add reviewed physical retailer offers before running valuation.
8. Review other contents, geometry, room areas, and finally create the packet when ready.

## Understanding the screens

- **Provisional inventory** means Gemini found visible spine regions. It is not a final book count.
- **Physical identity unresolved** means you need to decide whether the region is a new book, the same book seen elsewhere, or should stay unresolved.
- **Visible text** is literal text read from the crop. It still needs identity review.
- **Reading complete** means a crop was processed; it does not mean the title or edition was accepted.
- **Book pricing unavailable** usually means no owned, physically accepted, identified book is ready to price yet.

The recognition page shows the original image with detected regions, reading crops, extracted text, job state, and the next action. It also links to the complete JSON evidence when needed.

## Common problems

| What you see | What to do |
| --- | --- |
| `Jobs: 0` after ending capture | Recognition was not started. Begin a shelf plan while the camera capture is active, then sweep again. |
| A detection says `already imported as provisional observations` | This is expected. Continue with the physical-review action buttons. |
| A reading is `partial` or `unreadable` | Review the crop; if necessary, capture a steadier, closer, better-lit shelf view. |
| The price button is disabled | Resolve the physical book and complete identity review first. |
| Gemini is unavailable | Check `.env`, restart with `--recognition --free-tier-confirmed --key-file .env`, then refresh the page. |

## Tests

Run browser checks:

```bash
node --test tests/*.test.mjs
```

Run the Python suite:

```bash
python -m unittest
```

## More detail

Technical design, operating procedures, data contracts, test records, limitations, and evaluation material are in [docs](docs/).

Useful starting points:

- [Architecture](docs/02-architecture.md)
- [Capture and measurement](docs/04-capture-measurement.md)
- [Identification and valuation](docs/05-identification-valuation.md)
- [Operations and delivery](docs/09-operations-delivery.md)
- [Current completion status](docs/46-project-completion-status.md)
