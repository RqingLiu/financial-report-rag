"""One entry point for datasets, saved-answer scoring and explicitly paid evaluation runs."""

import argparse
import runpy
import sys

from finrag.core.config import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name, help_text in {
        "run": "Run query-only cases through the live engine; uncached calls may cost money",
        "prepare-judge": "Build offline judge packets from saved traces and references",
        "export-judge": "Export human/LLM judge prompts; no API calls",
        "score": "Validate imported verdicts and score saved answers; no API calls",
    }.items():
        subs.add_parser(name, help=help_text, add_help=False)
    data = subs.add_parser(
        "check-data", help="Validate released compound / draft intent datasets offline"
    )
    data.add_argument("--dataset", choices=["compound", "intents", "all"], default="all")
    subs.add_parser("build-intents", help="Rebuild the unfrozen intent draft; no API calls")
    args, rest = parser.parse_known_args()
    if args.command in ("check-data", "build-intents"):
        if rest:
            parser.error("unrecognized arguments: " + " ".join(rest))
        if args.command == "build-intents":
            builders = [("build_golden_v3.py", False)]
        elif args.dataset == "compound":
            builders = [("build_golden_v2.py", True)]
        elif args.dataset == "intents":
            builders = [("build_golden_v3.py", True)]
        else:
            builders = [("build_golden_v2.py", True), ("build_golden_v3.py", True)]
        for name, check in builders:
            sys.argv = [name, *(["--check"] if check else [])]
            runpy.run_path(str(ROOT / "scripts" / name), run_name="__main__")
        return
    if args.command == "run":
        from finrag.evaluation.run import main as run

        sys.argv = ["evaluation run", *rest]
        run()
    else:
        from finrag.evaluation.answers import main as answers

        command = "prepare" if args.command == "prepare-judge" else args.command
        sys.argv = ["evaluation", command, *rest]
        answers()


if __name__ == "__main__":
    main()
