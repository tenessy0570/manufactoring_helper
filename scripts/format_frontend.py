"""Format application JavaScript; bundled vendor files are deliberately excluded."""

from pathlib import Path

import cssbeautifier
import jsbeautifier


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "app/web/static"
    options = jsbeautifier.default_options()
    options.indent_size = 2
    for path in sorted(root.rglob("*.js")):
        if "vendor" not in path.parts:
            path.write_text(
                jsbeautifier.beautify(path.read_text(encoding="utf-8"), options) + "\n",
                encoding="utf-8",
            )
    for path in sorted(root.rglob("*.css")):
        if "vendor" not in path.parts:
            path.write_text(
                cssbeautifier.beautify(path.read_text(encoding="utf-8")) + "\n", encoding="utf-8"
            )


if __name__ == "__main__":
    main()
