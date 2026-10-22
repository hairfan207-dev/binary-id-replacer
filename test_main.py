"""Per-user logging path and setup checks without a GUI or packaged runtime."""

import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import main


class LoggingTests(unittest.TestCase):
    def test_local_appdata(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}):
                self.assertEqual(main.get_log_path(), Path(folder) /
                                 'Binary ID Replacer' / 'binary_replacer.log')

    def test_unset_appdata(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main.get_log_path(), Path.home() /
                             'Binary ID Replacer' / 'binary_replacer.log')

    def test_empty_or_relative_appdata(self):
        for folder in ('', 'relative'):
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}):
                self.assertEqual(main.get_log_path(), Path.home() /
                                 'Binary ID Replacer' / 'binary_replacer.log')

    def test_configure_creates_writable_log(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}):
                with patch.object(main.logging, 'basicConfig') as config:
                    path = main.configure_logging()
                handler = config.call_args.kwargs['handlers'][0]
                try:
                    record = logging.LogRecord('test', logging.INFO, '', 1,
                                               'startup check', (), None)
                    handler.handle(record)
                    handler.flush()
                    self.assertIn('startup check', path.read_text())
                finally:
                    handler.close()


if __name__ == '__main__':
    unittest.main()
