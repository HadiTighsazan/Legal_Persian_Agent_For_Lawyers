"""
Sample tasks for testing Celery integration.
"""

from celery import shared_task
import time


@shared_task
def test_task(message: str):
    """A simple test task that prints a message."""
    print(f"Test task received: {message}")
    return f"Processed: {message}"


@shared_task
def long_running_task(seconds: int):
    """A long-running task for testing async processing."""
    print(f"Starting long running task for {seconds} seconds")
    time.sleep(seconds)
    return f"Completed after {seconds} seconds"