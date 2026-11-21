"""Guard: every OCPPTest subclass must be registered or explicitly excluded."""
import importlib
import pkgutil

import pytest

import runner
from tests.base import OCPPTest


def _all_test_classes():
    found = {}
    for sub in ("v16", "v201"):
        pkg = importlib.import_module(f"tests.{sub}")
        for m in pkgutil.iter_modules(pkg.__path__):
            mod = importlib.import_module(f"tests.{sub}.{m.name}")
            for obj in vars(mod).values():
                if (isinstance(obj, type) and issubclass(obj, OCPPTest)
                        and obj is not OCPPTest and obj.__module__ == mod.__name__):
                    found[obj] = f"{sub}.{m.name}.{obj.__name__}"
    return found


def _registered():
    reg = set()
    for cats in (runner.V16_TEST_CATEGORIES, runner.V201_TEST_CATEGORIES):
        for classes in cats.values():
            reg.update(classes)
    return reg


def test_every_test_class_registered_or_excluded():
    registered = _registered()
    missing = [name for cls, name in _all_test_classes().items()
               if cls not in registered and cls.__name__ not in runner.EXCLUDED_TESTS]
    assert not missing, f"Unregistered test classes (register or add to EXCLUDED_TESTS): {missing}"


def test_excluded_entries_exist_and_are_unregistered():
    by_name = {cls.__name__: cls for cls in _all_test_classes()}
    registered = _registered()
    for name, reason in runner.EXCLUDED_TESTS.items():
        assert name in by_name, f"EXCLUDED_TESTS names unknown class {name}"
        assert by_name[name] not in registered, f"{name} is both excluded and registered"
        assert reason


def test_default_order_covers_categories():
    cats = set(runner.V16_TEST_CATEGORIES) | set(runner.V201_TEST_CATEGORIES)
    assert cats <= set(runner.DEFAULT_CATEGORY_ORDER)


# ── found by running the tester against real chargers ────────────────────

def test_flatten_config_keeps_sections_so_timeout_is_honoured():
    from main import flatten_config
    flat = flatten_config({"timing": {"test_timeout": 25, "boot_timeout": 60}, "server": {"port": 1}})
    assert flat["timing"]["test_timeout"] == 25      # TestRunner reads this
    assert flat["test_timeout"] == 25 and flat["port"] == 1   # tests read flat keys


def test_runner_uses_cli_timeout():
    from main import flatten_config
    from runner import TestRunner
    assert TestRunner(flatten_config({"timing": {"test_timeout": 25}})).timeout == 25


def test_errors_are_not_a_pass():
    from main import exit_status
    from tests.base import Severity, TestResult, TestStatus

    def mk(status, sev=Severity.WARNING):
        r = TestResult.__new__(TestResult)
        r.status, r.severity = status, sev
        return r

    assert exit_status([mk(TestStatus.PASS)])[0] == 0
    code, msg = exit_status([mk(TestStatus.PASS), mk(TestStatus.ERROR)])
    assert code == 1 and "inconclusive" in msg
    assert exit_status([mk(TestStatus.FAIL, Severity.CRITICAL)])[0] == 2
