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
        args = ["--chip", "auto", "--port", port, "--baud", str(baud), "write-flash", "-z",
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
