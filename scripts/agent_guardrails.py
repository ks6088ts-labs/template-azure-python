"""Catch common destructive shell mistakes; not a sandbox or authorization boundary."""

import json
import re
import shlex
import sys
from pathlib import PurePosixPath


def rejection_reason(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return "Malformed shell command; review it manually."
    words = [PurePosixPath(argument).name for argument in tokens]
    for index, word in enumerate(words):
        following = tokens[index + 1 :]
        if (
            word == "git"
            and "push" in following
            and any(argument == "-f" or argument.startswith("--force") for argument in following)
        ):
            return "Force-pushing requires explicit human approval."
        if word == "azd" and "down" in following:
            return "Azure teardown requires explicit human approval."
        if word == "az" and (
            "delete" in following
            or any(argument.lower() == "delete" or argument.lower().endswith("=delete") for argument in following)
        ):
            return "Azure resource deletion requires explicit human approval."
        if word == "rm" and any(argument.startswith("-") and "r" in argument for argument in following):
            if any(argument in {"/", "/*", "$HOME", "${HOME}", "~"} for argument in following):
                return "Recursive deletion of a root or home directory is prohibited."
    # Inspect common shell wrappers as well as ordinary tokenized commands.
    if re.search(r"\b(?:bash|sh|zsh)\s+-[a-z]*c\b", command):
        for argument in tokens:
            if any(character.isspace() for character in argument):
                reason = rejection_reason(argument)
                if reason:
                    return reason
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
        arguments = event.get("toolArgs", {})
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise ValueError("Expected tool arguments")
        command = arguments.get("command", "")
        if not isinstance(command, str):
            raise ValueError("Expected a shell command")
        reason = rejection_reason(command)
    except (ValueError, TypeError, AttributeError):
        reason = "Malformed tool request; review it manually."
    if reason:
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
