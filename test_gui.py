"""GUI integration checks using real Tk widgets and temporary binary files."""

from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import gui


class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.root.withdraw()
        self.app = gui.BinaryIDReplacerApp(self.root)
        self.addCleanup(self.root.destroy)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.source = Path(folder.name) / 'sample.bin'
        self.original = b'prefix' + (123).to_bytes(4, 'little') + b'tail'
        self.source.write_bytes(self.original)
        for name in ('showerror', 'showinfo', 'showwarning'):
            mock = patch.object(gui.messagebox, name)
            setattr(self, name, mock.start())
            self.addCleanup(mock.stop)
        self.app.file_path.set(str(self.source))
        self.app.old_id.set('123')
        self.app.new_id.set('456')

    def wait_for_job(self):
        deadline = time.monotonic() + 5
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.app.busy)
        for widget in (self.app.browse_button, self.app.old_entry,
                       self.app.new_entry, self.app.process_button):
            self.assertFalse(widget.instate(['disabled']))

    def test_preview_and_invalid_inputs(self):
        self.assertEqual(self.app.old_hex.get(), '7B 00 00 00')
        self.assertEqual(self.app.new_hex.get(), 'C8 01 00 00')
        for value in ('', '-1', '4294967296', '1.2', 'True', '0x10'):
            self.app.old_id.set(value)
            self.assertEqual(self.app.old_hex.get(), 'Invalid ID')
            self.assertTrue(self.app.process_button.instate(['disabled']))
        self.app.old_id.set('456')
        self.assertTrue(self.app.process_button.instate(['disabled']))

    def test_browse(self):
        with patch.object(gui.filedialog, 'askopenfilename',
                          return_value=str(self.source)) as dialog:
            self.app.browse_button.invoke()
        dialog.assert_called_once()
        self.assertEqual(self.app.file_path.get(), str(self.source))

    def test_success(self):
        self.app.process_button.invoke()
        self.wait_for_job()
        self.showinfo.assert_called_once()
        self.assertIn('Replacements Made: 1', self.showinfo.call_args.args[1])
        self.assertEqual(self.source.read_bytes(), self.original)
        output = self.app.output_path
        self.assertEqual(output.stat().st_size, len(self.original))
        self.assertEqual(output.read_bytes(), self.original.replace(
            (123).to_bytes(4, 'little'), (456).to_bytes(4, 'little')))

    def test_no_match(self):
        self.app.old_id.set('789')
        self.app.process()
        self.wait_for_job()
        self.showwarning.assert_called_once()
        self.assertEqual(self.app.status.get(), 'No matching ID found')
        self.assertIsNone(self.app.output_path)
        self.assertFalse((self.source.parent / 'sample_modified.bin').exists())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertTrue(self.app.folder_button.instate(['disabled']))
        self.assertIn('No modified file was created.',
                      self.showwarning.call_args.args[1])
        self.showinfo.assert_not_called()

    def test_failure_restores_controls(self):
        with patch.object(gui, 'replace_binary_ids',
                          side_effect=PermissionError('denied')):
            with self.assertLogs(gui.logger, 'ERROR'):
                self.app.process()
                self.wait_for_job()
        self.showerror.assert_called_once()
        self.assertEqual(self.app.status.get(), 'Processing failed')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_responsive_and_single_job(self):
        entered, release = threading.Event(), threading.Event()
        real_processor = gui.replace_binary_ids

        def delayed(*args):
            entered.set()
            release.wait(3)
            return real_processor(*args)

        with patch.object(gui, 'replace_binary_ids',
                          side_effect=delayed) as processor:
            self.app.process()
            self.assertTrue(entered.wait(2))
            try:
                ticks = []
                self.root.after(0, lambda: ticks.append(True))
                self.root.update()
                self.assertEqual(ticks, [True])
                self.assertTrue(self.app.busy)
                self.assertTrue(self.app.old_entry.instate(['disabled']))
                self.app.process()
                self.app._close()
                processor.assert_called_once()
                self.assertTrue(self.root.winfo_exists())
            finally:
                release.set()
            self.wait_for_job()

    def test_development_id_previews(self):
        self.app.old_id.set('10100400')
        self.app.new_id.set('101004046')
        self.assertEqual(self.app.old_hex.get(), 'B0 1E 9A 00')
        self.assertEqual(self.app.new_hex.get(), '0E 33 05 06')
        for value in (True, False, 123, None):
            with self.assertRaises(TypeError):
                gui.parse_id(value)

    def test_zero_match_delete_failure(self):
        self.app.old_id.set('789')
        real_unlink = Path.unlink

        def deny_output(path, *args, **kwargs):
            if path.name == 'sample_modified.bin':
                raise PermissionError('locked')
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', deny_output):
            with self.assertLogs(gui.logger, 'ERROR'):
                self.app.process()
                self.wait_for_job()
        self.assertEqual(self.source.read_bytes(), self.original)
        output = self.source.parent / 'sample_modified.bin'
        self.assertEqual(output.read_bytes(), self.original)
        self.assertIn('could not be removed', self.showwarning.call_args.args[1])
        self.assertTrue(self.app.folder_button.instate(['disabled']))
        self.assertIsNone(self.app.output_path)

    def test_worker_finished_and_progress_hidden(self):
        self.app.process()
        self.wait_for_job()
        self.assertIsNone(self.app.worker)
        self.assertFalse(self.app.progress.winfo_manager())

    def test_windows_folder_button(self):
        # Patch only the GUI's OS reference: changing global os.name on macOS
        # would make pathlib incorrectly try to construct WindowsPath objects.
        from types import SimpleNamespace
        from unittest.mock import Mock
        opener = Mock()
        fake_os = SimpleNamespace(name='nt', startfile=opener)
        with patch.object(gui, 'os', fake_os):
            self.app.process()
            self.wait_for_job()
            self.assertFalse(self.app.folder_button.instate(['disabled']))
            self.app.open_output_folder()
            opener.assert_called_once_with(str(self.source.parent))
            self.app.old_id.set('789')
            self.app.process()
            self.wait_for_job()
            self.assertTrue(self.app.folder_button.instate(['disabled']))
            self.app.open_output_folder()
            opener.assert_called_once()

    def test_folder_open_failure(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        self.app.output_path = self.source.parent / 'output.bin'
        fake_os = SimpleNamespace(
            name='nt', startfile=Mock(side_effect=OSError('unavailable')))
        with patch.object(gui, 'os', fake_os):
            with self.assertLogs(gui.logger, 'ERROR'):
                self.app.open_output_folder()
        self.showerror.assert_called_once()

    def test_thread_start_failure(self):
        with patch.object(gui.threading.Thread, 'start',
                          side_effect=RuntimeError('unavailable')):
            with self.assertLogs(gui.logger, 'ERROR'):
                self.app.process()
        self.assertFalse(self.app.busy)
        self.assertIsNone(self.app.worker)
        self.assertFalse(self.app.process_button.instate(['disabled']))
        self.showerror.assert_called_once()

    def test_file_removed_before_processing(self):
        self.source.unlink()
        with self.assertLogs(gui.logger, 'ERROR'):
            self.app.process()
        self.showerror.assert_called_once()
        self.assertFalse(self.app.busy)


if __name__ == '__main__':
    unittest.main()
