# Contributing to CHEMVAULT

Thank you for your interest in contributing to CHEMVAULT.

CHEMVAULT is maintained by the
[NanoBiostructures Research Group](https://nanobiostructuresrg.github.io)
at Tecnológico de Monterrey. Contributions that improve correctness,
reproducibility, usability, documentation, testing, or supported workflows are
welcome.

## How to Contribute

### Reporting Bugs

Open an issue on
[GitHub Issues](https://github.com/NanoBiostructuresRG-lab/chemvault/issues)
and include, when relevant:

- a clear description of the problem;
- the expected and observed behavior;
- a minimal reproducible example;
- the CHEMVAULT and Python versions;
- the operating system and installation method;
- the command, API call, or configuration involved;
- the relevant traceback or error output.

Do not include confidential, proprietary, or sensitive datasets in public
issues.

### Suggesting Features

Open an issue describing:

- the problem or use case;
- the proposed behavior;
- why it would be useful beyond a single workflow;
- any expected effect on the public API, CLI, configuration, outputs, or on
  scientific, provenance, persistence, or output contracts.

### Submitting a Pull Request

1. Fork the repository.
2. Create a descriptive branch from `main`.
3. Make a focused set of changes.
4. Add or update tests when behavior changes.
5. Run the relevant validation locally.
6. Push your branch and open a pull request against `main`.

Pull requests should pass CI before merge. User-facing changes should include
appropriate documentation and changelog updates.

## Development Setup

Create an environment with Python 3.12 using the environment manager you
prefer, then install CHEMVAULT in editable mode with the validation tools used
by CI:

```bash
git clone https://github.com/NanoBiostructuresRG-lab/chemvault.git
cd chemvault
python -m pip install -e . "ruff==0.17.0" "mypy==2.4.0" pytest build "twine>=7.0.0"
```

To work on the documentation:

```bash
python -m pip install -e ".[docs]"
mkdocs serve
```

## Testing

Run the complete test suite before opening a pull request:

```bash
python -m pytest tests -q
```

Changes should include tests when they modify behavior, fix a bug, add or
modify a scientific calculation or data-processing rule, change configuration
handling, alter generated outputs, or affect a public interface.

For documentation changes, also run:

```bash
mkdocs build --strict
```

## Code Style

Keep changes focused and consistent with the existing codebase. Use clear
names, type hints where appropriate, and docstrings consistent with the
surrounding modules.

Avoid unrelated refactoring or formatting changes in the same pull request.

## Scientific and Evaluation Changes

Changes that affect PubChem acquisition or target correspondence, structured
activity processing, molecular harmonization, activity-label consolidation,
MODELABILITY INDEX calculations, structural-context metrics, provenance, or
persisted outputs require particular care.

Such contributions should:

- explain the scientific or methodological rationale;
- identify affected input populations, molecular and activity identities,
  eligibility rules, and numerical calculations;
- distinguish PubChem acquisition, molecular harmonization, and downstream
  analytical outcomes;
- identify changes to scientific, provenance, persistence, and output
  contracts;
- preserve existing behavior and contracts when they are not part of the
  proposed change;
- justify and document intentional changes to established scientific behavior
  or contracts;
- include tests covering the changed behavior and relevant invariants;
- maintain reproducibility through explicit parameters, deterministic
  ordering, and provenance where applicable;
- update documentation and the changelog when appropriate.

## Documentation and Changelog

Update the relevant documentation when a change affects:

- public behavior;
- the CLI or Python API;
- configuration;
- supported scientific workflows;
- input requirements;
- generated outputs;
- examples or documented workflows.

Add an entry to `CHANGELOG.md` for user-visible changes. Purely internal
refactoring normally does not require a changelog entry unless it changes
observable behavior.

## Compatibility

CHEMVAULT is pre-stable, so public interfaces may evolve before version 1.0.
Compatibility changes should nevertheless be intentional, documented, tested,
and explained in the pull request.

Avoid changing public API symbols, CLI behavior, configuration keys, output
schemas, or serialized-artifact behavior without explicit justification.

## Pull Request Scope

Keep pull requests focused on one coherent change. Avoid combining feature
work, broad refactoring, formatting changes, and unrelated cleanup in the same
pull request.

Small, reviewable changes are easier to validate scientifically and
technically.

## Code of Conduct

Participation in CHEMVAULT is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Questions

For questions about contributing, open a GitHub issue. Sensitive
conduct-related matters should follow the private reporting process described
in the [Code of Conduct](CODE_OF_CONDUCT.md).
