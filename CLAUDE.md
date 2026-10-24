# Working notes for Claude on this repository

Read `docs/GHID.md` first: it is the owner's guide to the integration and the record of where work stopped (owner's installation, stage texts, scheme table, release process, open items). `PARAMETERS.md` is the entity reference, `CHANGELOG.md` the version history.

## How the owner wants to work

- Reply in **Romanian**. Keep everything the integration shows in Home Assistant (entity names, state texts) in **English**.
- **Approved changes go straight to `main`** (owner's decision, 23.10.2026, replacing the earlier pull-request flow). Commit on `claude/git-release-commit-f8oo83`, run the checks below, push the branch, then fast-forward `main` to it with `git push origin HEAD:main`. No pull requests unless the owner asks for one. Never force-push `main`; the one exception was the history rewrite of 24.10.2026 that removed personal data, approved by the owner.
- **Releases are automatic.** `.github/workflows/release.yml` runs on every push to `main`: when the manifest `version` has no `v<version>` release yet, it runs Validate, Hassfest and HACS, then creates the tag and the release with the notes from that version's `CHANGELOG.md` section (no section, no release). So a release is: bump the version (see below), write its changelog section, push to `main`. Sessions cannot create releases or tags themselves (GitHub refuses them for this session type); the workflow does it with the repository's own token.
- The project is **independent** since 1.0.0. It began as a fork of `9a4gl/hass-centrometal-boiler` (credited in `README.md` and `NOTICE`); never open pull requests or issues against that repository.
- `CLAUDE.md` and `docs/GHID.md` are **internal notes**: `.gitattributes` (`export-ignore`) keeps them out of every release archive, and HACS installs only `custom_components/`. Keep it that way: never put notes under `custom_components/`, and add any new internal file to `.gitattributes`.
- **Propose before changing.** List the intended changes (what, why, source page, effect on the owner's boiler) and wait for approval. Implement only what was approved.
- **Do not break what works.** Existing entity IDs, entities and automations must keep working. Change a state text or a name only where it is actually wrong, and say exactly which strings changed. After any change to `Boiler State` texts, post the full list of states in chat so the owner can check the automations.
- **Do not present inferences as facts.** Cite the manual page or a capture. The owner's boiler is scheme 43: P1 is the DHW pump on K1, P2 the DHW recirculation pump, and the valve is automatic. Behaviour on other schemes comes from the manual, not from the owner's boiler.
- **No personal data in the repository**, in code, tests, fixtures, docs or commit messages: no e-mail addresses, serial numbers, portal installation ids, real locations, controller file names or credentials. Use placeholders (`SN000001`, id `1001`, "Example City", `USR:PelTec II - Example`). When data comes from the owner's portal or a capture, strip it before it is committed.
- The Centrometal manuals must **not** be committed (public repository). `docs/GHID.md` lists them with the relevant pages; ask the owner to upload them again when they are needed.

## Checks before every push

- `ruff check .` and `pytest`, with Home Assistant installed (`pip install homeassistant aiohttp pytest pytest-asyncio ruff "websockets>=13.1" "certifi>=2024.7.4" voluptuous`, Python 3.13+). Without Home Assistant, ten test modules are silently skipped.
- `tests_ha/` runs the integration in a real Home Assistant against a fake Centrometal cloud. It needs its own environment (`pip install -r tests_ha/requirements.txt`, Python 3.13) and runs with `pytest -c tests_ha/pytest.ini tests_ha`. Run it too before pushing a change to the integration's behaviour.
- A version bump touches `manifest.json`, the `README.md` badge and heading, `tests/test_repository_layout.py` and a new `CHANGELOG.md` section.
- `tests/test_operation_stage_labels.py` pins every `Boiler State` text. Change it only on purpose.
