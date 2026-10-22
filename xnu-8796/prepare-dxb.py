"""Make the pinned dxb patch loop fail if any numbered NABU patch fails."""
import sys
from pathlib import Path


def prepare(path):
    text = path.read_text(encoding="utf-8")
    old = '                warning "Skipping patch ${PATCH} (already upstream, previously applied, or malformed): ${APPLY_CHECK}"'
    new = '''                case "$(basename "$PATCH")" in
                    [0-9][0-9][0-9][0-9]-*)
                        error "Required NABU patch failed: ${PATCH}: ${APPLY_CHECK}"
                        exit 1
                        ;;
                    *)
                        warning "Skipping optional dxb patch ${PATCH}: ${APPLY_CHECK}"
                        ;;
                esac'''
    if text.count(old) != 1:
        raise SystemExit("Pinned dxb patch loop changed; refusing to patch build.sh")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
