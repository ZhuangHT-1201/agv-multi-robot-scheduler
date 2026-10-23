# Contributing

Contributions are welcome.

## Workflow

1. Fork the repository and create a focused branch.
2. Install the development requirements.
3. Add or update tests for behavioral changes.
4. Run the validation commands below.
5. Submit a pull request describing the change and its tradeoffs.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e ./ecbs_standalone
```

On PowerShell, activate with `.\.venv\Scripts\Activate.ps1`.

## Validation

```bash
python -m compileall app.py algorithms common simulation vda5050
python algorithms/check_ecbs.py
python algorithms/headless_test.py swap string revert
```

For user-interface changes, also start the app and verify scene creation,
loading, editing, simulation controls, and responsive layout.

## Code Style

- Keep modules focused and preserve the existing scheduler interfaces.
- Use descriptive English identifiers and comments.
- Prefer deterministic behavior in tests.
- Avoid hard-coded private hosts, credentials, personal details, or local paths.
- Document non-obvious planning heuristics next to the relevant constants.

## Commit Messages

Use a short imperative subject and explain non-trivial behavior changes in the
body. Keep unrelated refactors separate from algorithm changes.

## Pull Request Checklist

- The code runs on Python 3.9 through 3.12.
- New behavior is covered by a test or a reproducible scenario.
- Documentation is updated.
- No secrets or personal information are included.
- Third-party assets and data have compatible redistribution terms.
