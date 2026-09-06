from __future__ import annotations

import functools
import unittest

from translate_tts.compat.patch_manager import PatchManager


class PatchManagerTests(unittest.TestCase):
    def test_partial_install_can_be_rolled_back(self):
        class Target:
            value = "original"

        manager = PatchManager()
        manager.install(Target, "value", lambda original: "wrapped")
        self.assertEqual(Target.value, "wrapped")
        manager.rollback()
        self.assertEqual(Target.value, "original")
        self.assertFalse(manager.active)

    def test_later_wrapper_is_never_overwritten_on_unload(self):
        class Target:
            value = "original"

        manager = PatchManager()
        own_wrapper = object()
        manager.install(Target, "value", lambda original: own_wrapper)
        later_wrapper = object()
        Target.value = later_wrapper
        manager.rollback()
        self.assertIs(Target.value, later_wrapper)

    def test_repeated_install_by_same_manager_is_idempotent(self):
        class Target:
            value = "original"

        manager = PatchManager()
        first = manager.install(Target, "value", lambda original: object())
        second = manager.install(Target, "value", lambda original: object())
        self.assertIs(first, second)
        self.assertEqual(len(manager.records), 1)
        self.assertEqual(manager.records[0].generation, manager.generation)

    def test_new_manager_strips_and_deactivates_previous_generation(self):
        class Target:
            def method(self):
                return "original"

        original = Target.method
        old = PatchManager()
        old_wrapper = old.install(Target, "method", lambda wrapped: lambda self: "old")
        newer = PatchManager()
        new_wrapper = newer.install(
            Target, "method", lambda wrapped: lambda self: "new"
        )
        self.assertFalse(old.active)
        self.assertIs(new_wrapper.__translate_tts_original__, original)
        self.assertIsNot(new_wrapper.__translate_tts_original__, old_wrapper)
        newer.close()
        self.assertIs(Target.method, original)

    def test_copied_metadata_deactivates_old_generation_without_removing_outer(self):
        class Target:
            def method(self):
                return "original"

        old = PatchManager()
        old_wrapper = old.install(Target, "method", lambda wrapped: lambda self: "old")

        @functools.wraps(old_wrapper)
        def external(self):
            return old_wrapper(self)

        Target.method = external
        newer = PatchManager()
        newer.install(Target, "method", lambda wrapped: lambda self: "new")
        self.assertFalse(old.active)
        self.assertIs(newer.records[0].original, external)

    def test_instance_patch_rollback_removes_inherited_method_shadow(self):
        class Target:
            def method(self):
                return "class-original"

        target = Target()
        manager = PatchManager()
        manager.install(target, "method", lambda original: lambda: "wrapped")
        self.assertIn("method", target.__dict__)
        self.assertEqual(target.method(), "wrapped")

        Target.method = lambda self: "class-updated"
        manager.rollback()
        self.assertNotIn("method", target.__dict__)
        self.assertEqual(target.method(), "class-updated")

    def test_instance_patch_restores_preexisting_own_attribute(self):
        class Target:
            def method(self):
                return "class"

        target = Target()
        own = lambda: "instance"
        target.method = own
        manager = PatchManager()
        manager.install(target, "method", lambda original: lambda: "wrapped")
        manager.rollback()
        self.assertIs(target.__dict__["method"], own)

    def test_new_generation_preserves_inherited_descriptor_ownership(self):
        class Target:
            def method(self):
                return "original"

        target = Target()
        old = PatchManager()
        old.install(target, "method", lambda original: lambda: "old")
        newer = PatchManager()
        newer.install(target, "method", lambda original: lambda: "new")
        newer.rollback()
        self.assertNotIn("method", target.__dict__)
        self.assertEqual(target.method(), "original")


if __name__ == "__main__":
    unittest.main()
