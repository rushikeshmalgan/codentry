"""Hard resource limits for the analysis pipeline, in one place.

Repository content is hostile input, so every dimension an attacker controls
(file count, file size, total bytes, path length, finding volume, tool
runtime, tool memory) has an explicit ceiling here. Exceeding a ceiling must
fail loudly or be recorded as an incomplete analysis — never be silently
truncated and reported as complete.
"""

from __future__ import annotations

MAX_FILES = 200  # analyzable files per snapshot (base or head)
MAX_FILE_BYTES = 500_000  # one source file
MAX_TOTAL_BYTES = 8_000_000  # all files in one snapshot
MAX_PATH_CHARS = 400
MAX_FINDINGS = 1_000  # per snapshot; beyond this the result is marked truncated

TOOL_TIMEOUT_SECONDS = 30
TOOL_MAX_OUTPUT_BYTES = 20_000_000

NODE_MAX_OLD_SPACE_MB = 512
SEMGREP_MAX_MEMORY_MB = 1_024
SEMGREP_RULE_TIMEOUT_SECONDS = 10
SEMGREP_RULE_TIMEOUT_THRESHOLD = 3

MAX_TRUSTED_CONFIG_BYTES = 64_000
MAX_TRUSTED_CONFIG_RULES = 500
