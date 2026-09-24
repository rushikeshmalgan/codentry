"""Codentry evaluation harness: measures what each review signal finds, on cases
with known ground truth.

The harness may import from `services/ai-review/analysis`; production code must
never import this package (enforced by services/ai-review/tests/test_scope_guards.py).
"""
