"""Firmware install over USB with esptool (the same layout the web flasher uses)."""
import contextlib
import io
import os
import tempfile

APP_OFFSET = 0x10000
OTADATA = (0xE000, 0x2000)   # erased so the board starts the newly written app


def check_image(data):
    if len(data) < 1024 or data[0] != 0xE9:
        return "not an ESP32 app image"
    if len(data) > 0x10000 and data[0x8000:0x8002] == b"\xaa\x50":
        return "this is a merged (full) image - use the app .bin, or the web flasher for a full install"
    return None


def native_usb(port):
    """True when the board's USB is the ESP32's own (Espressif 0x303A), not a USB-serial chip."""
    try:
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            if p.device.lower() == str(port).lower():
                return p.vid == 0x303A
    except Exception:
        pass
    return False


def flash_app(port, data, baud=460800):
    """Blocking. Writes the app image and restarts the board. Returns esptool's output."""
    import esptool
    problem = check_image(data)
    if problem:
        raise ValueError(problem)
    fd, path = tempfile.mkstemp(suffix=".bin")
    fd2, blank = tempfile.mkstemp(suffix=".bin")
    out = io.StringIO()
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        with os.fdopen(fd2, "wb") as f:
            f.write(bytes([0xFF]) * OTADATA[1])
        # Boards wired straight to the ESP32's own USB (T-Deck and friends) ignore the usual
        # reset line, and would sit in the flasher instead of starting the new firmware.
        after = "watchdog-reset" if native_usb(port) else "hard-reset"
        args = ["--chip", "auto", "--port", port, "--baud", str(baud), "--after", after, "write-flash", "-z",
                hex(OTADATA[0]), blank, hex(APP_OFFSET), path]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            esptool.main(args)
    except SystemExit as err:
        raise RuntimeError(f"esptool failed ({err.code}): {out.getvalue()[-400:]}")
    except Exception as err:
        raise RuntimeError(f"{err}: {out.getvalue()[-400:]}")
    finally:
        os.unlink(path)
        os.unlink(blank)
    return out.getvalue()
