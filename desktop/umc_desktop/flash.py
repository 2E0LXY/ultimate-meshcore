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


def looks_bootable(head):
    """head: the first 0x8002 bytes of the board's flash. An app-only update needs a bootloader
    and a partition table already in place; on an erased board it would write an app nothing
    can start."""
    if len(head) < 0x8002:
        return False
    boot_ok = head[0] == 0xE9 or head[0x1000] == 0xE9          # ESP32-S3 at 0x0, classic ESP32 at 0x1000
    return boot_ok and head[0x8000:0x8002] == b"\xaa\x50"


NO_BOOTLOADER = ("this board has no bootloader or partition table (its flash looks erased), so an app-only "
                 "update could not start. Do a full install first: the web flasher with 'erase' ticked, or "
                 "the merged .bin written at 0x0")


def read_head(port, baud=460800):
    """The first 0x8002 bytes of flash, to see whether the board has something to boot."""
    import esptool
    fd, path = tempfile.mkstemp(suffix=".bin")
    os.close(fd)
    out = io.StringIO()
    try:
        args = ["--chip", "auto", "--port", port, "--baud", str(baud), "--after", "no-reset", "read-flash",
                "0x0", hex(0x8002), path]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            esptool.main(args)
        with open(path, "rb") as f:
            return f.read()
    except SystemExit as err:
        raise RuntimeError(f"could not read the board ({err.code}): {out.getvalue()[-300:]}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


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
    if not looks_bootable(read_head(port, baud)):
        raise ValueError(NO_BOOTLOADER)
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
        for f in (path, blank):
            try:
                os.unlink(f)
            except OSError:
                pass   # Windows can still hold the handle briefly; the temp file is harmless
    return out.getvalue()
