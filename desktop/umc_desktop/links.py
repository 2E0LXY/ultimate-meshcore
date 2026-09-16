"""Connections to a radio: USB serial, WiFi (TCP port 5000) and Bluetooth.

Companion radios speak the MeshCore app protocol. Over USB and TCP each frame is sent as
'<' + length (2 bytes, little endian) + payload and received as '>' + length + payload.
Over Bluetooth each write / notification is one frame.
"""
import asyncio
import threading

import serial
import serial.tools.list_ports

BLE_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
BLE_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # we write here
BLE_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # radio notifies here
MAX_FRAME = 176


class LinkClosed(Exception):
    pass


class Deframer:
    """Splits a byte stream into '>'-framed payloads, skipping anything else (boot messages)."""

    def __init__(self, on_frame):
        self.buf = bytearray()
        self.on_frame = on_frame

    def feed(self, data):
        self.buf += data
        while True:
            start = self.buf.find(b">")
            if start < 0:
                self.buf.clear()
                return
            if start:
                del self.buf[:start]
            if len(self.buf) < 3:
                return
            n = self.buf[1] | (self.buf[2] << 8)
            if n == 0 or n > MAX_FRAME:
                del self.buf[:1]
                continue
            if len(self.buf) < 3 + n:
                return
            frame = bytes(self.buf[3:3 + n])
            del self.buf[:3 + n]
            self.on_frame(frame)


def frame_bytes(payload):
    return b"<" + len(payload).to_bytes(2, "little") + payload


class Link:
    """Base class. on_frame(bytes) is called on the event loop; on_close(reason) once."""

    kind = ""
    port = None     # serial port name, when the link is USB

    def __init__(self):
        self.on_frame = lambda f: None
        self.on_close = lambda reason: None
        self.label = ""
        self._closed = False

    def _closed_by_peer(self, reason):
        if not self._closed:
            self._closed = True
            self.on_close(reason)

    async def open(self):
        raise NotImplementedError

    async def send(self, payload):
        raise NotImplementedError

    async def close(self):
        self._closed = True


# ---------------------------------------------------------------- USB serial
def open_serial(port, baud=115200):
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.timeout = 0.2
    s.dtr = False     # leave the ESP32 auto-reset lines alone: opening must not restart the board
    s.rts = False
    s.open()
    return s


def list_serial_ports():
    out = []
    for p in serial.tools.list_ports.comports():
        if p.vid is None and not p.device.startswith(("/dev/ttyACM", "/dev/ttyUSB")):
            continue
        out.append({"port": p.device, "description": p.description or p.device,
                    "vid": p.vid, "pid": p.pid, "serial": p.serial_number or ""})
    return out


class SerialReader:
    """Reads a serial port on a thread and hands the bytes to the event loop."""

    def __init__(self, ser, loop, on_data, on_error):
        self.ser = ser
        self.loop = loop
        self.on_data = on_data
        self.on_error = on_error
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            try:
                data = self.ser.read(self.ser.in_waiting or 1)
            except Exception as err:  # unplugged
                if self.running:
                    self.loop.call_soon_threadsafe(self.on_error, str(err))
                return
            if data:
                self.loop.call_soon_threadsafe(self.on_data, data)

    def stop(self):
        self.running = False


class SerialFrameLink(Link):
    kind = "usb"

    def __init__(self, port, ser=None):
        super().__init__()
        self.port = port
        self.label = f"USB {port}"
        self.ser = ser
        self.reader = None
        self.deframer = Deframer(lambda f: self.on_frame(f))

    async def open(self):
        loop = asyncio.get_running_loop()
        if self.ser is None:
            self.ser = await loop.run_in_executor(None, open_serial, self.port)
        self.reader = SerialReader(self.ser, loop, self.deframer.feed, lambda e: self._closed_by_peer(e))

    async def send(self, payload):
        if self._closed:
            raise LinkClosed("not connected")
        try:
            self.ser.write(frame_bytes(payload))
        except Exception as err:
            self._closed_by_peer(str(err))
            raise LinkClosed(str(err))

    async def close(self):
        await super().close()
        if self.reader:
            self.reader.stop()
        try:
            self.ser.close()
        except Exception:
            pass


class SerialTextLink(Link):
    """Repeater command line over USB. request() sends '@umc <req>' and returns the JSON text."""

    kind = "usb"

    def __init__(self, port, ser=None):
        super().__init__()
        self.port = port
        self.label = f"USB {port}"
        self.ser = ser
        self.reader = None
        self.buf = bytearray()
        self.waiter = None
        self.plain_waiter = None
        self.lock = asyncio.Lock()

    async def open(self):
        loop = asyncio.get_running_loop()
        if self.ser is None:
            self.ser = await loop.run_in_executor(None, open_serial, self.port)
        self.reader = SerialReader(self.ser, loop, self._feed, lambda e: self._closed_by_peer(e))

    def _feed(self, data):
        self.buf += data
        while b"\n" in self.buf:
            line, _, rest = self.buf.partition(b"\n")
            self.buf = bytearray(rest)
            text = line.decode("utf-8", "replace").rstrip("\r")
            if text.startswith("@umc {") or text.startswith("@umc ["):
                if self.waiter and not self.waiter.done():
                    self.waiter.set_result(text[5:])
            elif text.startswith("  -> "):
                if self.plain_waiter and not self.plain_waiter.done():
                    self.plain_waiter.set_result(text[5:])

    async def request(self, req, timeout=8.0):
        if len(req) > 150:
            raise ValueError("command too long for USB (150 characters max)")
        async with self.lock:
            self.waiter = asyncio.get_running_loop().create_future()
            self._write(f"@umc {req}\r")
            try:
                return await asyncio.wait_for(self.waiter, timeout)
            finally:
                self.waiter = None

    async def command(self, line, timeout=5.0):
        """Plain command line (repeaters without the desktop bridge): returns the reply text."""
        async with self.lock:
            self.plain_waiter = asyncio.get_running_loop().create_future()
            self._write(line[:150] + "\r")
            try:
                return await asyncio.wait_for(self.plain_waiter, timeout)
            except asyncio.TimeoutError:
                return ""
            finally:
                self.plain_waiter = None

    def _write(self, text):
        if self._closed:
            raise LinkClosed("not connected")
        try:
            self.ser.write(text.encode())
        except Exception as err:
            self._closed_by_peer(str(err))
            raise LinkClosed(str(err))

    async def close(self):
        await super().close()
        if self.reader:
            self.reader.stop()
        try:
            self.ser.close()
        except Exception:
            pass


# ---------------------------------------------------------------- WiFi (TCP 5000)
class TcpFrameLink(Link):
    kind = "tcp"

    def __init__(self, host, port=5000):
        super().__init__()
        self.host, self.tcp_port = host, port
        self.label = f"WiFi {host}:{port}"
        self.writer = None
        self.task = None

    async def open(self):
        reader, self.writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.tcp_port), 8)
        deframer = Deframer(lambda f: self.on_frame(f))

        async def pump():
            try:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    deframer.feed(data)
            except Exception:
                pass
            self._closed_by_peer("connection closed")

        self.task = asyncio.create_task(pump())

    async def send(self, payload):
        if self._closed or self.writer is None:
            raise LinkClosed("not connected")
        self.writer.write(frame_bytes(payload))
        await self.writer.drain()

    async def close(self):
        await super().close()
        if self.writer:
            self.writer.close()
        if self.task:
            self.task.cancel()


# ---------------------------------------------------------------- Bluetooth
async def scan_ble(seconds=5.0):
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    out = []
    for dev, adv in found.values():
        name = adv.local_name or dev.name or ""
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        if BLE_SERVICE in uuids or name.startswith(("MeshCore", "UMC", "Ultimate")):
            out.append({"address": dev.address, "name": name or dev.address, "rssi": adv.rssi})
    out.sort(key=lambda d: -(d["rssi"] or -200))
    return out


class BleFrameLink(Link):
    kind = "ble"

    def __init__(self, address, name=""):
        super().__init__()
        self.address = address
        self.label = f"Bluetooth {name or address}"
        self.client = None

    async def open(self):
        from bleak import BleakClient
        self.client = BleakClient(self.address, disconnected_callback=lambda c: self._closed_by_peer("Bluetooth disconnected"))
        await self.client.connect(timeout=15)
        try:
            await self.client.pair()   # the operating system asks for the PIN shown on the radio
        except Exception:
            pass
        await self.client.start_notify(BLE_TX, lambda _c, data: self.on_frame(bytes(data)))

    async def send(self, payload):
        if self._closed or self.client is None:
            raise LinkClosed("not connected")
        await self.client.write_gatt_char(BLE_RX, payload, response=True)

    async def close(self):
        await super().close()
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
