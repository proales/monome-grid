# Just toggles grid buttons on and off.

#! /usr/bin/env python3

import asyncio
import monome
import monome.device as monome_device
from monome.exceptions import NoDevicesFoundError


# Compatibility layer for the newer monome Python API (which dropped GridApp/GridBuffer).
# Also provides a dummy grid so the script can run without hardware attached.
class _DummyGrid:
    def __init__(self, width=16, height=8):
        self.width = width
        self.height = height
        self.handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)

    def led_level_row(self, x_offset, y, levels):
        # No-op fallback when no physical grid is connected.
        pass


class _GridBuffer:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.levels = [[0 for _ in range(width)] for _ in range(height)]

    def led_level_set(self, x, y, level):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.levels[y][x] = level

    def render(self, grid):
        for y, row in enumerate(self.levels):
            grid.led_level_row(0, y, row)


class _GridApp:
    def __init__(self):
        # Patch monome.device.MonomeDevice to accept any connected model (e.g. "128").
        if not getattr(monome_device, "_gridstudies_patched", False):
            original_init = monome_device.MonomeDevice.__init__

            def patched_init(self, model_name: str = "one", prefix: str = "monome"):
                self.prefix = prefix
                self.handlers = []

                serialosc = monome_device.SerialOSC()
                serialosc.await_devices()

                available_devices = list(
                    filter(lambda device: device.device_model == model_name, serialosc.available_devices)
                )
                if not available_devices and serialosc.available_devices:
                    # Fall back to first available device (handles models like "128").
                    available_devices = [serialosc.available_devices[0]]

                try:
                    device = available_devices[0]
                except IndexError:
                    raise NoDevicesFoundError("No matching monome devices found")

                self.dispatcher = monome_device.Dispatcher()
                self.dispatcher.map(f"/sys/port", self._osc_handle_sys_port)
                self.dispatcher.set_default_handler(self._osc_handle_unknown_message)

                self.server = monome_device.ThreadingOSCUDPServer(
                    (monome_device.MONOME_HOST, 0), self.dispatcher
                )
                self.thread = monome_device.threading.Thread(
                    target=self.server.serve_forever, daemon=True
                )
                self.thread.start()
                self.server_port = self.server.socket.getsockname()[1]

                self.client = monome_device.SimpleUDPClient(monome_device.MONOME_HOST, device.port)
                self.client.send_message("/sys/port", [self.server_port])

            monome_device.MonomeDevice.__init__ = patched_init
            monome_device._gridstudies_patched = True

        try:
            self.grid = monome.Grid()
            self.connected = True
        except NoDevicesFoundError:
            # Gracefully degrade so the script can still run; LED updates become no-ops.
            print("No monome grid detected; running with dummy grid.")
            self.grid = _DummyGrid()
            self.connected = False
        self.grid.add_handler(self._dispatch_grid_key)

    def _dispatch_grid_key(self, event):
        if hasattr(self, "on_grid_key"):
            self.on_grid_key(event.x, event.y, int(event.down))


GridAppBase = getattr(monome, "GridApp", _GridApp)
GridBuffer = getattr(monome, "GridBuffer", _GridBuffer)


class GridStudies(GridAppBase):
    def __init__(self):
        super().__init__()
        self.width = self.grid.width
        self.height = self.grid.height
        self.sequencer_rows = self.height - 2
        self.step = [[0 for col in range(self.width)] for row in range(self.height)]
        self.play_position = -1
        self.next_position = -1
        self.cutting = False
        self.loop_start = 0
        self.loop_end = self.width - 1
        self.keys_held = 0
        self.key_last = 0
        self.play_task = asyncio.create_task(self.play())
        self.on_grid_ready()

    # when grid is plugged in via USB:
    def on_grid_ready(self):
        self.width = self.grid.width
        self.height = self.grid.height
        self.sequencer_rows = self.height - 2
        self.connected = True
        self.draw()

    def on_grid_disconnect(self,*args):
        self.connected = False

    async def play(self):
        while True:
            await asyncio.sleep(0.1)

            if self.cutting:
                self.play_position = self.next_position
            elif self.play_position == self.width - 1:
                self.play_position = 0
            elif self.play_position == self.loop_end:
                self.play_position = self.loop_start
            else:
                self.play_position += 1

            # TRIGGER SOMETHING
            for y in range(self.sequencer_rows):
                if self.step[y][self.play_position] == 1:
                    self.trigger(y)

            self.cutting = False

            if self.connected:
                self.draw()

    def trigger(self, i):
        print("triggered", i)

    def draw(self):
        buffer = GridBuffer(self.width, self.height)

        # display steps (no moving playhead highlight)
        for x in range(self.width):
            for y in range(self.sequencer_rows):
                buffer.led_level_set(x, y, self.step[y][x] * 11)

        # update grid
        buffer.render(self.grid)

    def on_grid_key(self, x, y, s):
        # toggle steps
        if s == 1 and y < self.sequencer_rows:
            self.step[y][x] ^= 1
            self.draw()
        # cut and loop
        elif y == self.height-1:
            self.keys_held = self.keys_held + (s * 2) - 1
            # cut
            if s == 1 and self.keys_held == 1:
                self.cutting = True
                self.next_position = x
                self.key_last = x
            # set loop points
            elif s == 1 and self.keys_held == 2:
                self.loop_start = self.key_last
                self.loop_end = x

async def main():
    grid_studies = GridStudies()
    await asyncio.get_running_loop().create_future()

if __name__ == '__main__':
    asyncio.run(main())
