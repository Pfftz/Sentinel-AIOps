import asyncio
import logging
import math
import random
import sys
import time
from typing import List

from fastapi import FastAPI, Request, Response
import structlog
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Configure standard logging to output to stdout
logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=logging.INFO,
)

# Configure structlog for JSON logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger(__name__)

app = FastAPI(
    title="Sentinel-Target-API",
    description="API for AIOps and SRE testing with simulated failure modes.",
    version="1.0.0"
)

# Prometheus Metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "http_status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)

# Global list for memory leak simulation
MEMORY_LEAK_STORE: List[str] = []


@app.middleware("http")
async def monitor_requests(request: Request, call_next):
    start_time = time.time()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception as e:
        logger.error("unhandled_exception", error=str(
            e), path=request.url.path, type=type(e).__name__)
        raise e
    finally:
        latency = time.time() - start_time

        # Record Prometheus metrics
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            http_status=status_code
        ).inc()

        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(latency)

        # Structured JSON log
        logger.info(
            "request_processed",
            method=request.method,
            path=request.url.path,
            status=status_code,
            duration_s=latency
        )


@app.get("/health")
async def health_check():
    """Health check endpoint returning 200 OK."""
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    """Exposes Prometheus metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/stress/cpu")
async def stress_cpu(duration: int = 5):
    """
    Simulates high CPU load by calculating primes for a given duration (seconds).
    Note: This is a blocking operation in an async function, which will intentionally
    starve the event loop and simulate severe CPU contention for the entire app.
    """
    logger.info("cpu_stress_started", duration=duration)
    start_time = time.time()
    primes_found = 0
    num = 2

    # CPU intensive loop
    while time.time() - start_time < duration:
        is_prime = True
        for i in range(2, int(math.sqrt(num)) + 1):
            if num % i == 0:
                is_prime = False
                break
        if is_prime:
            primes_found += 1
        num += 1

    logger.info("cpu_stress_completed", duration=duration,
                primes_found=primes_found)
    return {"message": f"CPU stress test completed for {duration} seconds", "primes_found": primes_found}


@app.get("/stress/memory")
async def stress_memory(megabytes: int = 10):
    """Simulates a memory leak by appending large strings to a global list."""
    logger.info("memory_stress_started", megabytes=megabytes)

    # Create a ~1MB string and append it to the global store
    mb_string = "A" * (1024 * 1024)
    for _ in range(megabytes):
        MEMORY_LEAK_STORE.append(mb_string)

    current_size_mb = len(MEMORY_LEAK_STORE)
    logger.info("memory_stress_completed", current_size_mb=current_size_mb)
    return {"message": f"Added {megabytes}MB to memory.", "total_leaked_mb": current_size_mb}


@app.get("/stress/latency")
async def stress_latency(min_delay: float = 1.0, max_delay: float = 5.0):
    """Simulates network/DB latency with random delays."""
    delay = random.uniform(min_delay, max_delay)
    logger.info("latency_stress_started", delay=delay)

    await asyncio.sleep(delay)

    logger.info("latency_stress_completed", delay=delay)
    return {"message": f"Simulated latency of {delay:.2f} seconds"}


@app.get("/stress/crash")
async def stress_crash():
    """Simulates service instability by raising a random unhandled exception."""
    exceptions = [
        ValueError("Simulated ValueError: Invalid configuration"),
        KeyError("Simulated KeyError: Missing critical key"),
        ConnectionError("Simulated ConnectionError: Database unreachable"),
        ZeroDivisionError(
            "Simulated ZeroDivisionError: Division by zero in calculation")
    ]
    chosen_exception = random.choice(exceptions)

    logger.warning("crash_stress_triggered",
                   exception_type=type(chosen_exception).__name__)

    # Raise the exception to simulate a crash
    raise chosen_exception
