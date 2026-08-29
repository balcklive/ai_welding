"""Generate a small deterministic signal fixture for the Playwright training flow."""

import csv
import math
from pathlib import Path

output = Path(__file__).resolve().parents[1] / "data" / "synthetic_training_signal.csv"
output.parent.mkdir(parents=True, exist_ok=True)

with output.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["time", "Current", "Voltage", "GasSpeed", "WireSpeed"])
    for index in range(500):
        t = index / 1000
        active = 0.10 <= t <= 0.44
        current = 0.0 if not active else 210 + 18 * math.sin(index / 11)
        voltage = 0.0 if not active else 23 + 2.2 * math.sin(index / 17)
        gas = 42 + 1.5 * math.sin(index / 23)
        wire = 7.2 + 0.6 * math.sin(index / 19)
        writer.writerow([f"{t:.3f}", f"{current:.4f}", f"{voltage:.4f}", f"{gas:.4f}", f"{wire:.4f}"])

print(output)
