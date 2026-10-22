#!/usr/bin/env python3
"""Reuse pure fixtures from the pinned UniXNU tree without executing its CLI."""
import ast
import struct
import zlib


def nvram_proxy(framework):
    source = framework / "scripts/qemu-entry/make-dt.py"
    module = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    functions = [item for item in module.body
                 if isinstance(item, ast.FunctionDef) and item.name == "empty_nvram_proxy"]
    if len(functions) != 1:
        raise ValueError("pinned UniXNU empty_nvram_proxy fixture is absent or ambiguous")
    # The upstream generator parses CLI arguments at module scope. Load only
    # its existing pure function; keep its original source and license intact.
    scope = {"struct": struct, "zlib": zlib}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), scope)
    return scope["empty_nvram_proxy"]()
