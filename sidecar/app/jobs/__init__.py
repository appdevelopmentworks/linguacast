"""Resumable job layer: pipeline state machine + per-stage artifact persistence.

A long job (e.g. a 10h video) must resume from the last successful stage rather
than restarting. Implemented in a later session.
"""
