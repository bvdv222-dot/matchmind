"""Traces and logs to Application Insights when APPLICATIONINSIGHTS_CONNECTION_STRING is set (it is on Azure).

Azure Monitor's OpenTelemetry distro installs the exporters; Agent Framework's instrumentation then emits a span for
every workflow, executor, agent run and model call, so one note's whole path shows up as one trace.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("matchmind")


def setup() -> bool:
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn:
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(connection_string=conn, logger_name="matchmind")
        from agent_framework.observability import enable_instrumentation
        enable_instrumentation(enable_sensitive_data=False)   # spans and timings, not prompt text
        return True
    except Exception as e:      # telemetry must never stop the app
        log.warning("telemetry setup failed: %s", e)
        return False
