#!/usr/bin/env python3
"""Ensure a protected device cannot generate a raw userdata image or flash instruction."""
import argparse
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--framework", type=Path, required=True)
args, extra = parser.parse_known_args()
sys.path.insert(0, str(args.framework.resolve() / "scripts"))
from unixnu import userdata
from unixnu.util import Error


class PreservationTests(unittest.TestCase):
    def test_preservation_blocks_before_tools_ipsw_or_output(self):
        context = SimpleNamespace(board={"userdata": {"preserve_existing": True}})
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), patch.object(userdata, "tool") as tool, \
                    patch.object(userdata, "Ipsw") as source, \
                    patch.object(userdata, "paths") as paths:
                with self.assertRaisesRegex(Error, "preserve_existing"):
                    userdata.build(context, dry_run)
                tool.assert_not_called()
                source.assert_not_called()
                paths.assert_not_called()

    def test_unprotected_boards_retain_the_tool_check(self):
        for spec in ({"first_lba": 1}, {"preserve_existing": False}):
            context = SimpleNamespace(board={"userdata": spec})
            with self.subTest(spec=spec), patch.object(userdata, "tool", side_effect=Error("tool check")):
                with self.assertRaisesRegex(Error, "^tool check$"):
                    userdata.build(context)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *extra])
