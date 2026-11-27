"""Small reproducible benchmark for optimized and unoptimized Rifa'i bytecode.

Run with:
    python benchmarks/benchmark_pipeline.py
    python benchmarks/benchmark_pipeline.py --iterations 20000 --repeat 7

The benchmark reports measurements from the local machine; it intentionally
does not encode performance claims or enforce timing thresholds in CI.
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rifai.compiler import Compiler
from rifai.vm import VirtualMachine

SOURCE_TEMPLATE = """\
let total: int = 0;
let index: int = 0;
while (index < {iterations}) {{
    total = total + (2 * 3 + 4);
    index = index + 1;
}}
print(total);
"""


def measure(callable_, repeat: int) -> tuple[float, float]:
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        callable_()
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples), min(samples)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()
    if args.iterations < 1 or args.repeat < 1:
        parser.error("--iterations and --repeat must be positive integers.")

    source = SOURCE_TEMPLATE.format(iterations=args.iterations)
    compiled = {
        "optimized": Compiler(optimize=True).compile(source, source_name="benchmark.rif"),
        "unoptimized": Compiler(optimize=False).compile(source, source_name="benchmark.rif"),
    }
    if any(not item.is_success for item in compiled.values()):
        raise SystemExit("Benchmark source failed to compile.")

    vm = VirtualMachine(max_steps=max(1_000_000, args.iterations * 20))
    expected_output = (str(args.iterations * 10),)
    measurements = {}
    for name, result in compiled.items():
        execution = vm.execute(result.module)
        if execution.output != expected_output:
            raise SystemExit(f"{name} execution produced unexpected output: {execution.output}")
        median_ms, best_ms = measure(lambda: vm.execute(result.module), args.repeat)
        instruction_count = len(result.module.main.instructions)
        measurements[name] = (median_ms, best_ms, instruction_count)
        print(
            f"{name:>10}: median={median_ms:9.3f} ms  "
            f"best={best_ms:9.3f} ms  "
            f"main-bytecode={instruction_count:4d} instructions"
        )

    baseline = measurements["unoptimized"][0]
    optimized = measurements["optimized"][0]
    if optimized > 0:
        print(f"Median runtime ratio (unoptimized / optimized): {baseline / optimized:.2f}x")
    print(
        "Executed VM instructions per optimized run: "
        f"{vm.execute(compiled['optimized'].module).instructions_executed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
