"""Unit checks for deterministic Haware property-test infrastructure."""
from pathlib import Path
import json
import unittest

from hypothesis import Phase
from hypothesis.strategies import SearchStrategy

from tests.property_support import config
from tests.property_support import strategies


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PropertyConfigurationTest(unittest.TestCase):
    def test_hypothesis_is_exactly_pinned_in_existing_environment_file(self):
        environment = (PROJECT_ROOT / "environment.yml").read_text(encoding="utf-8")
        self.assertIn("hypothesis==6.112.1", environment)
        self.assertEqual(config.HYPOTHESIS_VERSION, "6.112.1")

    def test_ci_settings_run_at_least_one_hundred_cases_and_replay_failures(self):
        self.assertGreaterEqual(config.PROPERTY_SETTINGS.max_examples, 100)
        self.assertTrue(config.PROPERTY_SETTINGS.print_blob)
        self.assertIsNotNone(config.PROPERTY_SETTINGS.database)
        self.assertIn(Phase.reuse, config.PROPERTY_SETTINGS.phases)
        self.assertGreaterEqual(config.CI_SEED, 0)

    def test_failure_metadata_is_stable_and_complete(self):
        identity = "a" * 64
        encoded = config.failure_metadata(
            replay_identity=identity,
            profile_identity=identity,
            run_identity=identity,
        )
        decoded = json.loads(encoded)
        self.assertEqual(decoded["ci_seed"], config.CI_SEED)
        self.assertEqual(decoded["hypothesis_version"], "6.112.1")
        self.assertEqual(decoded["replay_identity"], identity)
        self.assertEqual(encoded, json.dumps(decoded, sort_keys=True, separators=(",", ":")))

    def test_numbered_property_decorator_enforces_a_dedicated_module(self):
        def misplaced_property():
            pass

        with self.assertRaisesRegex(RuntimeError, "test_property_01"):
            config.deterministic_property(1)(misplaced_property)


class StrategySurfaceTest(unittest.TestCase):
    def test_every_required_bounded_strategy_is_available(self):
        factories = (
            strategies.valid_calibrations,
            strategies.degenerate_calibrations,
            strategies.poses,
            strategies.nuisance_cases,
            strategies.nuisance_profiles,
            strategies.nuisance_vectors,
            strategies.observations,
            strategies.observation_records,
            strategies.semantic_alternatives,
            strategies.support_boundaries,
            strategies.track_provenance,
            strategies.populations,
            strategies.decisions,
            strategies.evidence_gate_decisions,
        )
        for factory in factories:
            with self.subTest(strategy=factory.__name__):
                self.assertIsInstance(factory(), SearchStrategy)

    def test_bounded_float_strategy_rejects_no_endpoints(self):
        self.assertIsInstance(strategies.bounded_floats(-1.0, 1.0), SearchStrategy)


if __name__ == "__main__":
    unittest.main()
