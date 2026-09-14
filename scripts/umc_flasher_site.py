"""Assemble the GitHub Pages web flasher from CI build artifacts.

Usage: python scripts/umc_flasher_site.py <artifacts_dir> <site_dir>

<artifacts_dir>/<env>/ must contain bootloader.bin, partitions.bin, boot_app0.bin,
firmware.bin and firmware-merged.bin (one folder per PlatformIO env, e.g.
umc_heltec_v3_repeater). The site gets flasher/index.html, one ESP Web Tools
manifest per env and builds.json describing everything, so the page always
offers exactly the builds from the latest run.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BOARDS = {
    "heltec_v3": ("Heltec V3 / V3.2", "ESP32-S3"),
    "heltec_v4_oled": ("Heltec V4 (OLED)", "ESP32-S3"),
    "heltec_v4_tft": ("Heltec V4 (TFT)", "ESP32-S3"),
    "heltec_v4_r8_oled": ("Heltec V4 R8 (OLED)", "ESP32-S3"),
    "heltec_v4_r8_tft": ("Heltec V4 R8 (TFT)", "ESP32-S3"),
    "ttwr_sx1262": ("LilyGo T-TWR + SX1262", "ESP32-S3"),
}
ROLES = {
    "repeater": ("Repeater", "Relays mesh traffic; WiFi web UI"),
    "companion": ("Client (companion)", "Use with the MeshCore apps"),
    "room_server": ("Room server", "Shared message board"),
}
CHIP_FAMILY = {"ESP32-S3": "ESP32-S3", "ESP32": "ESP32", "ESP32-C3": "ESP32-C3"}


def umc_version():
    with open(os.path.join(ROOT, "variants", "umc", "platformio.ini"), encoding="utf-8") as f:
        m = re.search(r"UMC_VERSION='\"([^\"]+)\"'", f.read())
    return m.group(1) if m else "dev"


def git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    except Exception:
        return ""


def split_env(env):
    name = env[len("umc_"):]
    for role in sorted(ROLES, key=len, reverse=True):
        if name.endswith("_" + role):
            return name[: -len(role) - 1], role
    return name, "repeater"


def main(artifacts, site):
    version = umc_version()
    commit = os.environ.get("GITHUB_SHA") or git("rev-parse", "HEAD")
    repo = os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/" + os.environ.get("GITHUB_REPOSITORY", "")
    os.makedirs(site, exist_ok=True)
    shutil.copy(os.path.join(ROOT, "flasher", "index.html"), os.path.join(site, "index.html"))

    builds = []
    for env in sorted(os.listdir(artifacts)):
        src = os.path.join(artifacts, env)
        needed = ["bootloader.bin", "partitions.bin", "boot_app0.bin", "firmware.bin", "firmware-merged.bin"]
        if not os.path.isdir(src) or not all(os.path.exists(os.path.join(src, n)) for n in needed):
            print(f"skip {env}: incomplete artifacts")
            continue
        board, role = split_env(env)
        board_label, chip = BOARDS.get(board, (board, "ESP32-S3"))
        role_label, role_help = ROLES.get(role, (role, ""))
        dst = os.path.join(site, "firmware", env)
        os.makedirs(dst, exist_ok=True)
        app_name = f"ultimate-meshcore-{version}-{env[4:]}.bin"
        merged_name = f"ultimate-meshcore-{version}-{env[4:]}-merged.bin"
        for n in ["bootloader.bin", "partitions.bin", "boot_app0.bin", "firmware.bin"]:
            shutil.copy(os.path.join(src, n), os.path.join(dst, n))
        shutil.copy(os.path.join(src, "firmware.bin"), os.path.join(dst, app_name))
        shutil.copy(os.path.join(src, "firmware-merged.bin"), os.path.join(dst, merged_name))

        manifest = {
            "name": f"Ultimate MeshCore - {board_label} {role_label}",
            "version": f"{version} ({commit[:7]})",
            "home_assistant_domain": None,
            "new_install_prompt_erase": True,
            "builds": [{
                "chipFamily": CHIP_FAMILY.get(chip, chip),
                "parts": [
                    {"path": "bootloader.bin", "offset": 0x0},
                    {"path": "partitions.bin", "offset": 0x8000},
                    {"path": "boot_app0.bin", "offset": 0xE000},
                    {"path": "firmware.bin", "offset": 0x10000},
                ],
            }],
        }
        del manifest["home_assistant_domain"]
        with open(os.path.join(dst, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        builds.append({
            "env": env, "board": board, "board_label": board_label, "chip": chip,
            "role": role, "role_label": role_label, "role_help": role_help,
            "manifest": f"firmware/{env}/manifest.json",
            "app": f"firmware/{env}/{app_name}",
            "merged": f"firmware/{env}/{merged_name}",
        })

    info = {
        "version": version,
        "commit": commit,
        "built": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "repo": repo,
        "builds": builds,
    }
    with open(os.path.join(site, "builds.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    # GitHub Pages: serve files as-is
    open(os.path.join(site, ".nojekyll"), "w").close()
    print(f"site ready: {len(builds)} build(s), version {version}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
