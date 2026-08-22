"""5EAT TCU car-CAN simulator.

Drives the full monitored CAN bus (engine + body/chassis) from a live vehicle
physics model so the 2006 Tribeca 5EAT TCU runs as if installed in a moving car,
and closes the loop on the TCU's commanded gear. Built on the firmware-derived
CAN catalog (CAN_CATALOG.md / CAN_MAP_RAW.md).
"""
__version__ = "0.1.0"
