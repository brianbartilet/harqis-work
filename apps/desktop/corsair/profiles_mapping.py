#!/usr/bin/env python
"""
Dump Corsair iCUE profiles (cueprofile / cueprofiledata) to a readable text file.

What it does
------------
- Scans a folder for:
    - *.cueprofiledata  (hardware profiles)
    - *.cueprofile      (software profiles, if any)
- For each profile:
    - Extracts profile name and ID
    - Walks the <actions> section
    - For each action, extracts:
        - which key/button (MouseG1, Mouse3, etc.)
        - the action's display name (e.g. "Hotkey - [1] Share")
        - the keystroke combo (for internal parsing only)

Output format
-------------
- Profiles are sorted alphabetically by profile name.
- Header per profile:

    =====================================================  (55 '=')
    Profile: <ProfileName>
    =====================================================

- No GUID shown in the header.
- The file path / GUID line is removed entirely.
- Only two columns:

    Key / Button         →  Action Name

- Actions with empty/unassigned keys are skipped.
- Action name column is cleaned:
  trailing " [Something]" (like "[KeyRemapAction]" or "[Unknown]") is stripped.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import argparse
import re as _re


def parse_profile_actions(path: Path):
    """
    Parse a single .cueprofile or .cueprofiledata file and extract action mappings.

    Returns:
        (profile_name, actions)
    """
    try:
        tree = ET.parse(path)
    except Exception as e:
        return f"(ERROR parsing {path.name}: {e})", []

    root = tree.getroot()

    profile_node = root.find(".//profile")
    if profile_node is None:
        profile_node = root

    profile_name = (profile_node.findtext(".//name") or "(unnamed)").strip()
    profile_id = (profile_node.findtext(".//id") or "").strip()

    actions_node = profile_node.find(".//actions")
    actions = []

    if actions_node is None:
        return profile_name, actions

    for val in actions_node:
        first = val.find("./first")
        second = val.find("./second")

        polym_name = first.findtext(
            "./polymorphic_name", ""
        ).strip() if first is not None else ""

        key = second.findtext(
            "./key", ""
        ).strip() if second is not None else ""

        event = second.findtext(
            "./event", ""
        ).strip() if second is not None else ""

        data = first.find(
            "./ptr_wrapper/data"
        ) if first is not None else None

        base_name = None
        keystroke_combo = None

        if data is not None:
            base = data.find("./base")
            if base is not None:
                base_name = base.findtext("./name")
                if base_name:
                    base_name = base_name.strip()

            ks = data.find("./keyStroke")
            if ks is not None:
                keys = [
                    (child.text or "").strip()
                    for child in ks
                    if (child.text or "").strip()
                ]
                if keys:
                    keystroke_combo = "+".join(keys)

        actions.append(
            {
                "action_type": polym_name or "Unknown",
                "key": key,
                "event": event,
                "name": base_name,
                "keystroke": keystroke_combo,
                "profile_name": profile_name,
                "profile_id": profile_id,
            }
        )

    return profile_name, actions


def build_summary(
    profiles_dir: Path,
    output_filename: str = "icue_keymap_summary_detailed.txt",
    output_dir: str = None,
) -> (Path, str):

    profiles_dir = profiles_dir.resolve()
    all_profile_files = sorted(
        list(profiles_dir.glob("*.cueprofiledata")) +
        list(profiles_dir.glob("*.cueprofile"))
    )

    if not all_profile_files:
        raise FileNotFoundError(
            f"No .cueprofiledata or .cueprofile files found in {profiles_dir}"
        )

    parsed_profiles = []
    for path in all_profile_files:
        profile_name, actions = parse_profile_actions(path)
        parsed_profiles.append((profile_name.lower(), profile_name, path, actions))

    # sort alphabetically by profile name
    parsed_profiles.sort(key=lambda x: x[0])

    lines = []

    for _, profile_name, _path, actions in parsed_profiles:

        filtered_actions = [a for a in actions if a.get("key") and a["key"].strip()]

        lines.append("=" * 50)
        lines.append(f"Profile: {profile_name}")
        lines.append("=" * 50)

        if not filtered_actions:
            lines.append("  (No actions with assigned keys/buttons found)")
            lines.append("")
            continue

        lines.append("  Key / Button         >  Action Name")
        lines.append("  -----------------------------------------------")

        for a in filtered_actions:
            src = a["key"].strip()
            name_text = a["name"] or a["action_type"] or "(no name)"
            name_text = _re.sub(r"\s+\[[^\]]+\]\s*$", "", name_text).strip()
            lines.append(f"  {src:<15} >  {name_text}")

        lines.append("")
        lines.append("")

    # determine output directory
    if output_dir is None:
        target_dir = profiles_dir
    else:
        target_dir = Path(output_dir).expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

    out_path = target_dir / output_filename
    dump = "\n".join(lines)
    out_path.write_text(dump, encoding="utf-8")
    return out_path, dump


def main():
    parser = argparse.ArgumentParser(
        description="Extract iCUE key mappings into a readable text file."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Folder containing .cueprofile/.cueprofiledata files",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="icue_keymap_summary_detailed.txt",
        help="Output filename",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write output file (default: same as profile folder)",
    )

    args = parser.parse_args()
    profiles_dir = Path(args.path)

    out_path = build_summary(
        profiles_dir,
        output_filename=args.output,
        output_dir=args.output_dir
    )
    print(f"Written summary to: {out_path}")


if __name__ == "__main__":
    main()
