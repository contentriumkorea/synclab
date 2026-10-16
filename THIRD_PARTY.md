# Third-party components

SyncLab bundles separate shared libraries. They retain their own licenses.
The application source is available in the accompanying source archive/repository.

- Python: https://www.python.org/ ; PSF license.
- NumPy: https://numpy.org/ ; BSD and bundled dependency notices.
- SciPy: https://scipy.org/ ; BSD and bundled dependency notices.
- PyAV: https://github.com/PyAV-Org/PyAV ; BSD-3-Clause.
- FFmpeg shared libraries: https://ffmpeg.org/ ; this wheel reports LGPL v3 or later.
  Exact upstream version is recorded in LICENSES/runtime-versions.json.
  Source archives: https://ffmpeg.org/releases/ ; build scripts: https://github.com/PyAV-Org/pyav-ffmpeg
- Qt for Python / PySide6 / Shiboken: https://code.qt.io/pyside/pyside-setup.git/ ;
  LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only as stated by the installed wheel metadata.
  Licensing documentation: https://doc.qt.io/qtforpython-6/licenses.html
- PyInstaller bootloader: https://pyinstaller.org/ ; GPL with distribution exception.

Full available license notices are collected in LICENSES, including LGPLv3 and GPLv3.
Qt and FFmpeg libraries remain separate DLLs under _internal and can be replaced with
compatible modified builds. No source media, user projects, or analysis cache is bundled.
