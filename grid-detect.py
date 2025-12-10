# Small test file to detect if there is a grid attached.

import monome
from monome.serialosc import SerialOSC

try:
    s = SerialOSC()
    s.await_devices(timeout=1)
    print("Found:", s.available_devices)
except Exception as e:
    print("Error:", e)

