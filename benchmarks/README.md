# Rifa'i Benchmarks

Run the standard-library benchmark from the repository root:

```bash
python benchmarks/benchmark_pipeline.py
python benchmarks/benchmark_pipeline.py --iterations 20000 --repeat 7
```

The script compiles the same loop with optimization enabled and disabled, checks
that both versions produce identical output, then reports median and best VM
execution time plus generated main-chunk instruction counts.

Results depend on the Python version, hardware, and system load. Timing is
informational and is deliberately not a CI pass/fail threshold. The optimizer
currently performs conservative constant folding and removes the neutral
`DUP; POP` pair; it does not rewrite control-flow edges or change language
semantics.
