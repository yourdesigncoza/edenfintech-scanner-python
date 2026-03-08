from __future__ import annotations

import unittest

from edenfintech_scanner_bootstrap.regression import run_regression_suite
from edenfintech_scanner_bootstrap.validation import validate_assets


class BootstrapAssetsTest(unittest.TestCase):
    def test_validate_assets(self) -> None:
        report = validate_assets()
        self.assertTrue(report.ok, msg="\n".join(report.messages))

    def test_regression_suite(self) -> None:
        results = run_regression_suite()
        failures = [result for result in results if not result.passed]
        self.assertFalse(
            failures,
            msg="\n".join(
                f"{result.fixture_id}: {', '.join(result.details)}" for result in failures
            ),
        )


if __name__ == "__main__":
    unittest.main()
