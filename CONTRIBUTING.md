# Contributing to DMXReplay

Thanks for your interest in DMXReplay. This project is developed in phases (see the
roadmap in [README.md](README.md) and the plan in `docs/SPECIFICATION.md`); please check
open issues/PRs before starting large work to avoid duplicate effort.

## Ground rules

- **The specification is the source of truth.** Any change to the on-disk format
  (metadata schema, pixel packing, universe mapping) must be reflected in
  `docs/SPECIFICATION.md` *and* bump the format version per its versioning rules
  (§16 of the spec). Undocumented behavior required for compatibility is a bug.
- **Losslessness is non-negotiable.** Any change touching the codec/container layer must
  keep the round-trip tests in `tests/` (and `test-vectors/`) passing byte-for-byte.
- **Core engine stays GUI-independent.** Code under `src/dmxreplay/` other than
  `src/dmxreplay/ui` must not import GUI toolkits. GUIs and the CLI are consumers of the
  core API (`docs/API.md`), not the other way around.
- **No unnecessary scope.** Follow the phase currently being worked; don't fold in
  unrelated features (see the phase table in `README.md`).

## Development setup

```bash
git clone https://github.com/gnouBXL/dmxreplay
cd dmxreplay
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Making changes

1. Open an issue first for anything beyond a small fix, describing which phase/section
   of `docs/SPECIFICATION.md` it affects.
2. Write/update tests alongside the change. Format/codec changes need a test vector in
   `test-vectors/` when practical.
3. Run `pytest` before opening a PR.
4. Update `CHANGELOG.md` under "Unreleased".
5. Keep commits focused; describe *why*, not just *what*, in the commit message.

## Code style

- Python 3.10+, type hints on public functions.
- No dependency on a GUI toolkit inside `src/dmxreplay/*` core modules (see above).
- Prefer standard library / already-adopted dependencies (see `pyproject.toml`) before
  adding a new one — new dependencies should be justified in the PR description.

## Reporting issues

Please include: DMXReplay version, OS, the command/action, and — for format/decoding
issues — a minimal `.dmxr` file or test vector if possible.
