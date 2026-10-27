# LogFlow Pipeline - Increment 5

LogFlow is an extensible, modular log processing engine built with the **Pipes and Filters** architectural pattern and driven by declarative YAML configurations. Increment 5 adds a designed error strategy: per-stage error policies, a dead-letter channel, declarative validation and a run summary.

## Project Structure
- `src/`:
  - `interfaces.py`: Core Source, Sink, Stage abstractions; `StageException` (recoverable, per record), `PipelineException` (fatal) and `ConfigurationError`.
  - `policy.py`: `ErrorPolicy` (`FAIL_FAST`, `SKIP`, `DEAD_LETTER`, `RETRY(n)`).
  - `dead_letter.py`: `FailedRecord`, `DeadLetterChannel` (independent secondary pipeline), `DeadLetterFileSink` (JSON Lines).
  - `validation.py`: declarative `ValidationStage` (required fields, numeric ranges, timestamp consistency, IP format).
  - `summary.py`: `RunSummary` / `StageStats`.
  - `record.py`: Immutable `LogRecord` domain model.
  - `parser.py`: Common Log Format (CLF) parser stage (raises `StageException` instead of silently skipping).
  - `filters.py`: `PredicateFilterStage` (condition-based) and `ProjectionStage`.
  - `stages.py`: `FileLineSource`, `ConsoleSink`, and `FileSink`.
  - `pipeline.py`: Pipeline execution engine and fluent `PipelineBuilder`.
  - `registry.py`: Data-driven `StageRegistry` mapping stage names to factories.
  - `loader.py`: Declarative YAML loader with fail-fast validation.
  - `main.py`: CLI entry point supporting both `--config` and manual arguments.
- `configs/`:
  - `error-report.yaml`: Filters HTTP status >= 400.
  - `dirty-report.yaml`: Chaos-test pipeline (valid -> main sink, invalid -> dead-letter).
  - `api-traffic.yaml`: Extracts `/api` traffic.
  - `bandwidth-client.yaml`: Extracts client bandwidth for requests > 500 bytes.
- `tests/`:
  - `test_parser.py`: Parser unit tests (8 edge cases).
  - `test_stages.py`: Unit tests for PredicateFilter, Projection, and FileSink.
  - `test_integration.py`: End-to-end integration test.
  - `test_loader.py`: Validation tests for declarative configuration loader (incl. `on_error` / `dead_letter`).
  - `test_policies.py`: Error policy and dead-letter engine tests.
  - `test_validation.py`: ValidationStage rule tests.
  - `test_chaos.py`: Chaos test on `data/access-dirty.log` and `data/empty.log`.
- `data/`: `access-small.log`, `access-dirty.log` (deliberately corrupted), `empty.log`.
- `tools/make_dirty_log.py`: deterministic generator of the chaos-test inputs.
- `ARCHITECTURE.md`: Architecture, error model, policies, dead-letter pipeline, RunSummary and the error-type -> policy table.

---

## How to Run

### Run Pre-Configured Declarative Pipelines
```bash
# 1. Error Report
python src/main.py --config configs/error-report.yaml

# 2. API Traffic Extract
python src/main.py --config configs/api-traffic.yaml

# 3. Client Bandwidth Extract
python src/main.py --config configs/bandwidth-client.yaml

# 4. Chaos test: corrupted input -> run completes, every record accounted for
python src/main.py -c configs/dirty-report.yaml
#   63 incoming = 40 outgoing (out/dirty-clean.txt) + 23 dead-letter (out/dead-letter.jsonl)
```

### Manual mode
```bash
python src/main.py data/access-dirty.log --min-status 400 --dead-letter out/dl.jsonl --summary-json out/summary.json
```
Exit codes: `0` ok, `1` configuration error, `2` `PipelineException` at run time. A RunSummary is printed after every run.

### Run the tests
```bash
python -m unittest discover -s tests
```
