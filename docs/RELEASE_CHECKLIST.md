# Release Checklist

Use this checklist before tagging or sharing a new Aria demo build.

## Code and Dependencies

- Confirm dependency changes are reflected in both `pyproject.toml` and `uv.lock`.
- Run the automated test suite with `./scripts/run_tests.ps1`.
- Run `uv run python scripts/healthcheck.py` after changing providers, environment variables, or startup code.
- Confirm the application starts with `uv run python -m agent.bot -t webrtc`.

## Configuration

- Compare `.env.example` with the runtime settings documented in `README.md`.
- Make sure required keys are named but never committed with real values.
- Keep latency-related defaults documented when they change.
- Verify optional production settings are clearly marked as optional.

## Demo Flow

- Seed the database and run one appointment booking flow end to end.
- Test one FAQ answer and one human escalation path.
- End a call with a goodbye phrase and confirm the bot closes the session.
- Review generated metrics and latency logs for obvious regressions.

## Documentation

- Update `README.md` when commands or ports change.
- Update `docs/TEST_CHECKLIST.md` when new tools or caller flows are added.
- Update `DIAGNOSTICS.md` when new startup failures or provider errors are discovered.
- Keep production readiness warnings visible for healthcare use cases.
