# Amicor capability modules.
# Each module exposes:
#   TRIGGERS: list[str]  — lowercase keywords that activate this module
#   handle(message, history) -> str  — the response function
#
# To add a new capability:
#   1. Create modules/<name>.py with TRIGGERS and handle()
#   2. Add one entry to CAPABILITIES in router.py
