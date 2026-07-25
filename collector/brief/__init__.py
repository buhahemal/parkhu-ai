"""Brief layer — turns the day's derived CSVs into a decision-ready swing brief.

Deterministic only. Everything here is arithmetic over files the collector
already produced, under the numeric limits in config/risk.py. No opinions, no
network calls, no LLM.
"""
