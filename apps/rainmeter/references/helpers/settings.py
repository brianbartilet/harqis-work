import shutil
from pathlib import Path

def set_rainmeter_always_on_top(rainmeter_ini_path: str, value: int = -2):
    """
    Reads a UTF-16 LE Rainmeter.ini and sets AlwaysOnTop=value for all sections.
    Creates backup <Rainmeter.ini>.bak.
    """
    ini_path = Path(rainmeter_ini_path).expanduser().resolve()
    if not ini_path.exists():
        raise FileNotFoundError(f"Rainmeter.ini not found: {ini_path}")

    # Rainmeter.ini is UTF-16 LE, so we must read/write with utf-16
    backup_path = ini_path.with_suffix(ini_path.suffix + ".bak")
    shutil.copy2(ini_path, backup_path)

    output_lines = []
    in_section = False
    saw_aot = False

    with ini_path.open("r", encoding="utf-16") as f:
        for line in f:
            stripped = line.strip()

            # Start of new section
            if stripped.startswith("[") and stripped.endswith("]"):
                # If previous section had no AlwaysOnTop, inject it
                if in_section and not saw_aot:
                    output_lines.append(f"AlwaysOnTop={value}\n")

                output_lines.append(line)
                in_section = True
                saw_aot = False
                continue

            if in_section:
                # Replace AlwaysOnTop if exists
                if stripped.lower().startswith("alwaysontop"):
                    output_lines.append(f"AlwaysOnTop={value}\n")
                    saw_aot = True
                    continue

                # Blank line ends section
                if stripped == "":
                    if not saw_aot:
                        output_lines.append(f"AlwaysOnTop={value}\n")
                    output_lines.append(line)
                    in_section = False
                    continue

            output_lines.append(line)

    # Write back as UTF-16 so Rainmeter can read it
    with ini_path.open("w", encoding="utf-16") as f:
        f.writelines(output_lines)

    return str(ini_path)
