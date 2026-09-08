"""
WearTwin Telemetry Benchmark & Latency Profiling Tool
Measures real HTTP ingestion latency, batch sync throughput, and packet success rates.
Saves reproducible benchmark metrics to ml/saved_models/telemetry_benchmark.json.
"""

import time
import json
import statistics
import requests

BASE_URL = "http://127.0.0.1:8000"
PATIENT_ID = "3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2"
NUM_REQUESTS = 100

def run_benchmarks():
    print("=" * 65)
    print("  WearTwin Telemetry Benchmark & Latency Profiler")
    print("=" * 65)

    # 1. Check health
    try:
        t0 = time.perf_counter()
        res = requests.get(f"{BASE_URL}/health", timeout=3)
        health_lat = (time.perf_counter() - t0) * 1000.0
        if res.status_code != 200:
            print(f"ERROR: Backend returned status {res.status_code}. Make sure backend is running.")
            return
        print(f"[1/3] Backend is ONLINE (Health Check: {health_lat:.2f} ms)")
    except Exception as e:
        print(f"ERROR: Could not connect to {BASE_URL}. Start backend server first:\n  python backend/main.py")
        return

    # 2. Sequential Telemetry Ingestion Profiling (N=100)
    print(f"\n[2/3] Benchmarking Single Telemetry Ingestion (N={NUM_REQUESTS} requests)...")
    latencies = []
    successes = 0
    errors = 0

    sample_payload = {
        "patient_id": PATIENT_ID,
        "hr": 78.5,
        "spo2": 97.8,
        "temp": 36.8,
        "bp_sys": 120,
        "bp_dia": 78,
        "activity_level": 4.5
    }

    for i in range(NUM_REQUESTS):
        start_t = time.perf_counter()
        try:
            r = requests.post(f"{BASE_URL}/ingest", json=sample_payload, timeout=5)
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            if r.status_code in [200, 202]:
                successes += 1
                latencies.append(elapsed_ms)
            else:
                errors += 1
        except Exception:
            errors += 1

    mean_lat = statistics.mean(latencies) if latencies else 0.0
    median_lat = statistics.median(latencies) if latencies else 0.0
    min_lat = min(latencies) if latencies else 0.0
    max_lat = max(latencies) if latencies else 0.0
    p95_lat = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max_lat
    delivery_rate = (successes / NUM_REQUESTS) * 100.0

    print(f"  Requests Sent       : {NUM_REQUESTS}")
    print(f"  Successful (HTTP 200): {successes} ({delivery_rate:.1f}%)")
    print(f"  Failed / Dropped    : {errors}")
    print(f"  Mean Latency        : {mean_lat:.2f} ms")
    print(f"  Median Latency      : {median_lat:.2f} ms")
    print(f"  Min / Max Latency   : {min_lat:.2f} ms / {max_lat:.2f} ms")
    print(f"  95th Percentile     : {p95_lat:.2f} ms")

    # 3. Batch Ingestion Profiling (Offline-Queue Sync)
    print(f"\n[3/3] Benchmarking Offline Batch Ingestion Sync...")
    batch_sizes = [10, 25, 50, 100]
    batch_results = {}

    for b_size in batch_sizes:
        batch_events = [
            {
                "patient_id": PATIENT_ID,
                "hr": 75.0 + (j % 10),
                "spo2": 98.0,
                "temp": 36.7,
                "bp_sys": 118,
                "bp_dia": 76,
                "activity_level": 4.0
            }
            for j in range(b_size)
        ]
        b_payload = {"patient_id": PATIENT_ID, "events": batch_events}

        t_b_start = time.perf_counter()
        try:
            b_res = requests.post(f"{BASE_URL}/ingest/batch", json=b_payload, timeout=10)
            b_lat = (time.perf_counter() - t_b_start) * 1000.0
            if b_res.status_code == 200:
                per_event_lat = b_lat / b_size
                batch_results[f"batch_{b_size}"] = {
                    "total_ms": round(b_lat, 2),
                    "per_event_ms": round(per_event_lat, 2),
                    "status": "success"
                }
                print(f"  Batch Size {b_size:>3}: Total {b_lat:>6.2f} ms | Per-Event: {per_event_lat:>5.2f} ms")
            else:
                batch_results[f"batch_{b_size}"] = {"status": f"HTTP {b_res.status_code}"}
        except Exception as be:
            batch_results[f"batch_{b_size}"] = {"status": str(be)}

    # Save benchmark report to repo
    benchmark_report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "test_environment": "Localhost FastHTTP / FastAPI Uvicorn ASGI",
        "single_ingestion": {
            "total_requests": NUM_REQUESTS,
            "success_rate_pct": round(delivery_rate, 2),
            "mean_latency_ms": round(mean_lat, 2),
            "median_latency_ms": round(median_lat, 2),
            "min_latency_ms": round(min_lat, 2),
            "max_latency_ms": round(max_lat, 2),
            "p95_latency_ms": round(p95_lat, 2)
        },
        "batch_synchronization": batch_results
    }

    out_file = "ml/saved_models/telemetry_benchmark.json"
    with open(out_file, "w") as f:
        json.dump(benchmark_report, f, indent=2)

    print("\n" + "=" * 65)
    print(f"  [SAVED] Benchmark metrics saved to: {out_file}")
    print("=" * 65)

if __name__ == "__main__":
    run_benchmarks()
