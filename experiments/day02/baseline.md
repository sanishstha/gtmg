# Day 2 baseline

This is the live desk before routing. It is the 10 Oct 2026 run of `python scripts/run_pipeline.py` recorded in `DAY1.md`. A second pipeline run would skip documents that already have a successful extractor run, so these figures are not reproduced by re-running that command.

- current model: `gpt-4.1-mini`
- number of test documents: 30
- successful extractions: 53 events, 0 extraction failures
- failed extractions: 0
- average latency: 2.8s
- approximate cost: $0.0805

Schema validity on that run was 100%. Grounded events were 98%. The hypothesis agent is out of scope for the Day 2 exam. The 30-case ground-truth set is a separate measurement.
