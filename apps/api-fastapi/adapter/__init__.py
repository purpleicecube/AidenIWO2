"""Adapter package marker — kept lightweight on purpose.

Poll-handler registration moved to `main.py` so the parity CLIs
(`adapter.dispatch_gating_cli`, `adapter.gamma_request_shape_cli`)
don't transitively import wo_wf.transitions. The TS/Python parity
tests spawn those CLIs as subprocesses and need a minimal import
graph.
"""
