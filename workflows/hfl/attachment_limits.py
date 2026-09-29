"""Shared limits for uploaded and worker-restored HFL input files."""

MAX_FILES = 50
MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_TOTAL_BYTES = MAX_FILES * MAX_FILE_BYTES
