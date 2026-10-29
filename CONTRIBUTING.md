# Contributing

Thanks for helping make QueryDoctor better. This guide gets you from clone to pull request.

## Set up

```bash
git clone https://github.com/ContentbyShanu/querydoctor.git
cd querydoctor
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Daily workflow

```bash
pytest --cov                      # tests, 85% coverage minimum
ruff check src tests              # lint
ruff format src tests             # format
mypy                              # strict type checking
querydoctor seed --scale 0.1      # a small database for manual testing
querydoctor serve                 # dashboard at http://127.0.0.1:8000
```

`make check` runs lint, types and tests together on Linux and macOS.

## Where things live

| Change | Look in |
|---|---|
| New candidate rule (index shapes) | `src/querydoctor/candidates.py` and `tests/test_candidates.py` |
| Scoring or confidence | `src/querydoctor/ranker.py` and `docs/adr/0005-*.md` |
| A new database engine | `src/querydoctor/engine.py` (implement `Engine`), see `docs/ARCHITECTURE.md` |
| Dashboard | `src/querydoctor/web/static/` (plain ES modules and CSS, no build step) |

## Ground rules

- **No invented numbers.** If a change affects recommendations, run `querydoctor bench` and
  commit the regenerated `docs/benchmarks.md` and `docs/benchmarks.json`.
- **Never run destructive SQL against a user database.** New code that executes SQL must go
  through `validate_readonly` and the sandbox.
- **No new HTML files.** The dashboard is JavaScript and CSS; the live boot document is generated
  in `web/__init__.py`. The only HTML file is the GitHub Pages host page `index.html`. A test
  enforces this.
- Add type hints and a docstring to every public function, and a test for every behavior.
- Keep functions small and focused; delete dead code instead of commenting it out.

## Commits and pull requests

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
`test:`, `refactor:`, `chore:`. Keep commits focused. Fill in the pull request template and
make sure CI is green.

## Reporting bugs and ideas

Open an issue with the template. For security problems see `SECURITY.md`.
