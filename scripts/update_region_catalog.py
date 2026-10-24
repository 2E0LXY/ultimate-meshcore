"""Refresh the validated GB MeshCore region catalogue bundled with the flasher."""

import json
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "flasher" / "regions-gb.json"
SOURCE = "https://raw.githubusercontent.com/marcelverdult/meshcore-regions/main/regions/gb.json"
CODE = re.compile(r"^[a-z0-9-]{1,29}$")


def validate(node, seen):
    if not isinstance(node, dict) or not CODE.fullmatch(node.get("code", "")):
        raise ValueError(f"Invalid region node: {node!r}")
    if node["code"] in seen:
        raise ValueError(f"Duplicate region code: {node['code']}")
    seen.add(node["code"])
    if not isinstance(node.get("name"), str) or not node["name"].strip():
        raise ValueError(f"Missing name for {node['code']}")
    if not isinstance(node.get("regions"), list):
        raise ValueError(f"Missing child list for {node['code']}")
    for child in node["regions"]:
        validate(child, seen)


def main():
    request = urllib.request.Request(SOURCE, headers={"User-Agent": "ultimate-meshcore-region-updater"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    validate(data, set())
    if data["code"] != "gb":
        raise ValueError("Expected the GB root region")
    DESTINATION.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {DESTINATION}")


if __name__ == "__main__":
    main()
