import os
from collections.abc import Generator
from contextlib import contextmanager


@contextmanager
def telemetry_environment() -> Generator[None, None, None]:
    """Apply SDK-only controls for one emission, then restore the process environment."""
    controls = {
        "APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL": "true",
        "APPLICATIONINSIGHTS_SDKSTATS_DISABLED": "true",
        "APPLICATIONINSIGHTS_CONTROLPLANE_DISABLED": "true",
        "OTEL_TRACES_SAMPLER": "always_on",
    }
    previous = {name: os.environ.get(name) for name in controls}
    try:
        os.environ.update(controls)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
