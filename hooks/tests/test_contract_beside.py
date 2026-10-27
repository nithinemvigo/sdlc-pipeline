"""Loose contract matching in guard_context_budget.contract_beside.

Run from the repo root:  python -m unittest discover -s hooks/tests -v
"""
import importlib.util
import os
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(__file__), "..", "guard_context_budget.py")
spec = importlib.util.spec_from_file_location("guard_context_budget", HOOK)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class ContractBesideTest(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        os.makedirs("docs/features/emv", exist_ok=True)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def touch(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("x\n")

    def test_short_name_inside_longer_requirements_name_is_not_shadowed(self):
        self.touch("docs/features/export.requirements.contract.md")
        self.touch("docs/features/csv-export.requirements.md")
        self.assertIsNone(guard.contract_beside("docs/features/csv-export.requirements.md"))

    def test_unrelated_doc_is_not_shadowed_by_requirements_contract(self):
        self.touch("docs/features/user-auth.requirements.contract.md")
        self.touch("docs/auth.md")
        self.assertIsNone(guard.contract_beside("docs/auth.md"))

    def test_generic_requirements_doc_is_not_shadowed(self):
        self.touch("docs/features/billing.requirements.contract.md")
        self.touch("docs/requirements.md")
        self.assertIsNone(guard.contract_beside("docs/requirements.md"))

    def test_part_file_is_not_shadowed_by_other_feature(self):
        self.touch("docs/features/campaigns.requirements.contract.md")
        self.touch("docs/features/emv/02-campaigns.requirements.md")
        self.assertIsNone(guard.contract_beside("docs/features/emv/02-campaigns.requirements.md"))

    def test_exact_stem_contract_still_matches(self):
        self.touch("docs/features/export.requirements.contract.md")
        self.touch("docs/features/export.requirements.md")
        self.assertEqual(
            os.path.normpath(guard.contract_beside("docs/features/export.requirements.md")),
            os.path.normpath("docs/features/export.requirements.contract.md"),
        )

    def test_long_renamed_contract_still_matches(self):
        self.touch("docs/features/user-authentication-flow.contract.md")
        self.touch("docs/features/user-authentication-flow-spec.md")
        self.assertEqual(
            os.path.normpath(guard.contract_beside("docs/features/user-authentication-flow-spec.md")),
            os.path.normpath("docs/features/user-authentication-flow.contract.md"),
        )

    def test_short_original_inside_long_contract_is_not_shadowed(self):
        self.touch("docs/features/user-authentication-flow.contract.md")
        self.touch("docs/auth.md")
        self.assertIsNone(guard.contract_beside("docs/auth.md"))

    def test_long_renamed_requirements_contract_still_matches(self):
        self.touch("docs/features/user-authentication.requirements.contract.md")
        self.touch("docs/features/user-authentication-flow.requirements.md")
        self.assertEqual(
            os.path.normpath(guard.contract_beside("docs/features/user-authentication-flow.requirements.md")),
            os.path.normpath("docs/features/user-authentication.requirements.contract.md"),
        )


if __name__ == "__main__":
    unittest.main()
