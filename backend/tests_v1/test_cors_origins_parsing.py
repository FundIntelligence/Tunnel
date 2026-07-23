"""
PAR-83 regression test: CORS_ORIGINS parsing must tolerate both
comma-separated and space-separated values (and any mix of the two),
not just one exact delimiter convention.

Mirrors the parsing logic in backend/main.py:47-50 directly rather than
importing the FastAPI app, since app import pulls in the full v1 router
(Supabase client, migrations, etc.) which needs live credentials and a
newer Python version than some local dev environments have — out of
scope for a pure parsing-logic test.
"""
import re
import unittest


def _parse_cors_origins(value: str) -> list[str]:
    """Same logic as backend/main.py:50 — kept in sync intentionally."""
    origins = re.split(r"[\s,]+", value.strip())
    return sorted({o.strip() for o in origins if o.strip()})


class TestCorsOriginsParsing(unittest.TestCase):
    def test_space_separated(self):
        value = "https://app.paritytunnel.com https://paritytunnel.com http://localhost:3000"
        self.assertEqual(
            _parse_cors_origins(value),
            sorted(
                [
                    "https://app.paritytunnel.com",
                    "https://paritytunnel.com",
                    "http://localhost:3000",
                ]
            ),
        )

    def test_comma_separated(self):
        value = "https://app.paritytunnel.com,https://paritytunnel.com,http://localhost:3000"
        self.assertEqual(
            _parse_cors_origins(value),
            sorted(
                [
                    "https://app.paritytunnel.com",
                    "https://paritytunnel.com",
                    "http://localhost:3000",
                ]
            ),
        )

    def test_mixed_delimiters_matches_the_pre_par83_live_value(self):
        # The actual live CORS_ORIGINS value at time of investigation: five
        # space-separated origins plus one comma-prefixed origin appended
        # later as a workaround. Both formats must resolve identically.
        mixed = (
            "https://app.paritytunnel.com https://paritytunnel.com "
            "https://parity-tunnel.vercel.app http://localhost:3000 "
            "https://parity-sme-staging.vercel.app,https://demo.paritytunnel.com"
        )
        cleaned_comma_separated = (
            "https://app.paritytunnel.com,https://paritytunnel.com,"
            "https://parity-tunnel.vercel.app,http://localhost:3000,"
            "https://parity-sme-staging.vercel.app,https://demo.paritytunnel.com"
        )
        self.assertEqual(_parse_cors_origins(mixed), _parse_cors_origins(cleaned_comma_separated))
        self.assertIn("https://demo.paritytunnel.com", _parse_cors_origins(mixed))
        self.assertIn("https://app.paritytunnel.com", _parse_cors_origins(mixed))
        self.assertIn("https://paritytunnel.com", _parse_cors_origins(mixed))

    def test_old_comma_only_split_was_broken(self):
        # Documents the actual bug PAR-83 fixed: naive split(",") on a
        # space-separated value produces one unmatched blob instead of
        # distinct origins.
        mixed = (
            "https://app.paritytunnel.com https://paritytunnel.com "
            "https://parity-tunnel.vercel.app http://localhost:3000 "
            "https://parity-sme-staging.vercel.app,https://demo.paritytunnel.com"
        )
        old_broken_result = [o.strip() for o in mixed.split(",")]
        self.assertNotIn("https://app.paritytunnel.com", old_broken_result)
        self.assertNotIn("https://paritytunnel.com", old_broken_result)

    def test_empty_env_var_produces_no_origins(self):
        self.assertEqual(_parse_cors_origins(""), [])

    def test_extra_whitespace_and_repeated_delimiters_are_tolerated(self):
        value = "  https://a.example.com   ,,  https://b.example.com  "
        self.assertEqual(
            _parse_cors_origins(value),
            sorted(["https://a.example.com", "https://b.example.com"]),
        )


if __name__ == "__main__":
    unittest.main()
