import unittest

from remote_image.core.registry import PluginRegistry


class RegistryTests(unittest.TestCase):
    def test_register_and_get(self) -> None:
        registry = PluginRegistry()
        item = object()
        registry.register("example", item)
        self.assertIs(registry.get("example"), item)

    def test_duplicate_name_is_rejected(self) -> None:
        registry = PluginRegistry()
        registry.register("example", object())
        with self.assertRaises(ValueError):
            registry.register("example", object())


if __name__ == "__main__":
    unittest.main()
