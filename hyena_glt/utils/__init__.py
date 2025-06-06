"""
Hyena-GLT Utilities

This module provides utility functions and helper classes for the Hyena-GLT framework.
"""

# Import only what exists
from .analysis import analyze_tokenization, analyze_sequence_composition
from .performance import (
    ProfilerContext,
    benchmark_model,
    gpu_memory_usage,
    measure_throughput,
    memory_usage,
    monitor_resources,
)

__version__ = "1.0.1"
__author__ = "Hyena-GLT Development Team"

__all__ = [
    # Analysis functions
    "analyze_tokenization",
    "analyze_sequence_composition",
    # Performance monitoring
    "ProfilerContext",
    "memory_usage",
    "gpu_memory_usage",
    "benchmark_model",
    "measure_throughput",
    "monitor_resources",
]
