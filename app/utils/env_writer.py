from pathlib import Path
from shutil import copy2


def update_env_file(updates: dict[str, str]) -> dict[str, str]:
    if "OPENROUTER_API_KEY" in updates:
        raise ValueError("OPENROUTER_API_KEY must not be updated here")

    for value in updates.values():
        if "\n" in value or "\r" in value:
            raise ValueError("env value must not contain newlines")

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    remaining = dict(updates)
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue

        key, _ = line.split("=", 1)
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    if remaining:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        for key, value in remaining.items():
            new_lines.append(f"{key}={value}")

    new_content = "\n".join(new_lines) + "\n"
    backup_path = env_path.with_name(".env.bak")
    temp_path = env_path.with_name(".env.tmp")

    if env_path.exists():
        copy2(env_path, backup_path)

    temp_path.write_text(new_content, encoding="utf-8")
    temp_path.replace(env_path)
    return updates
