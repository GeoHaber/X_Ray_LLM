# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for X-Ray Standalone Web App (.exe)
=====================================================
Builds a self-contained Windows executable that runs the
full Streamlit-based X-Ray web interface without needing
Python, Streamlit, or any other package installed.

Bundles:
  - Full X-Ray scanner (AST smells, duplicates, reporting)
  - Streamlit web framework + static assets
  - Ruff linter (ruff.exe)
  - Bandit security scanner
  - x_ray_core Rust acceleration (.pyd)
  - numpy, pandas, pyarrow, etc (Streamlit deps)

Build command:
    python -m PyInstaller x_ray_web.spec --distpath X_Ray_Standalone --workpath build_web --noconfirm
"""

import os
import sys
import shutil
import importlib
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata, collect_submodules

# Project root
PROJECT = Path(SPECPATH)

# ─── Locate bundled tools/libs ────────────────────────────────────────────────

ruff_path = shutil.which("ruff") or str(PROJECT / ".venv" / "Scripts" / "ruff.exe")
x_ray_core_pyd = str(PROJECT / ".venv" / "Lib" / "site-packages" / "x_ray_core" / "x_ray_core.cp313-win_amd64.pyd")
if not os.path.isfile(x_ray_core_pyd):
    x_ray_core_pyd = str(PROJECT / "x_ray_core.pyd")

print(f"  [spec] ruff.exe:      {ruff_path}")
print(f"  [spec] x_ray_core:    {x_ray_core_pyd}")

# ─── Streamlit static assets ─────────────────────────────────────────────────

import streamlit as _st
_st_dir = os.path.dirname(_st.__file__)
print(f"  [spec] streamlit:     {_st_dir}")

# ─── Binaries ────────────────────────────────────────────────────────────────

binaries = []
if os.path.isfile(ruff_path):
    binaries.append((ruff_path, '.'))
if os.path.isfile(x_ray_core_pyd):
    binaries.append((x_ray_core_pyd, '.'))

# ─── Data files ──────────────────────────────────────────────────────────────

datas = [
    # The UI script itself (loaded by bootstrap.run at runtime)
    (str(PROJECT / "x_ray_ui.py"), '.'),

    # Streamlit's static frontend (HTML/JS/CSS) — CRITICAL
    (os.path.join(_st_dir, "static"), os.path.join("streamlit", "static")),

    # Streamlit's proto files
    (os.path.join(_st_dir, "proto"), os.path.join("streamlit", "proto")),
]

# x_ray_core package (init etc.)
xray_core_pkg = PROJECT / ".venv" / "Lib" / "site-packages" / "x_ray_core"
if xray_core_pkg.is_dir():
    datas.append((str(xray_core_pkg), 'x_ray_core'))

# ─── Package metadata (importlib.metadata needs .dist-info for version()) ────

_metadata_pkgs = [
    'streamlit', 'altair', 'pandas', 'numpy', 'pyarrow', 'tornado',
    'pydeck', 'blinker', 'cachetools', 'click', 'tenacity', 'toml',
    'watchdog', 'requests', 'urllib3', 'certifi', 'typing_extensions',
    'packaging', 'protobuf', 'Pillow', 'rich', 'gitpython',
]
for _pkg in _metadata_pkgs:
    try:
        datas += copy_metadata(_pkg)
    except Exception:
        print(f"  [spec] WARNING: no metadata for {_pkg} — skipping")


# ─── Hidden imports ──────────────────────────────────────────────────────────

hidden_imports = [
    # X-Ray project modules
    'Core', 'Core.types', 'Core.config', 'Core.utils', 'Core.inference',
    'Core.ast_helpers',
    'Analysis', 'Analysis.ast_utils', 'Analysis.smells', 'Analysis.duplicates',
    'Analysis.similarity', 'Analysis.lint', 'Analysis.security',
    'Analysis.reporting', 'Analysis.rust_advisor', 'Analysis.auto_rustify',
    'Analysis.test_gen', 'Analysis.tracer', 'Analysis.smart_graph',
    'Analysis.library_advisor', 'Analysis.transpiler',
    'Analysis.llm_transpiler', 'Analysis.port_project',
    'Analysis.semantic_fuzzer',
    'Core.llm_manager', 'Core.inference',
    '_mothership', '_mothership.hardware_detection', '_mothership.models',
    '_mothership.settings_service',
    'Lang', 'Lang.python_ast', 'Lang.tokenizer',

    # Streamlit — collect ALL submodules to avoid missing internal imports
    *collect_submodules('streamlit'),

    # Streamlit dependencies
    'altair', 'altair.vegalite', 'altair.vegalite.v5',
    'vl_convert',
    'blinker',
    'cachetools',
    'click',
    'gitdb', 'git', 'smmap',
    'numpy', 'numpy.core', 'numpy._core',
    'pandas', 'pandas.core', 'pandas.io',
    'PIL', 'PIL.Image',
    'pydeck',
    'pyarrow', 'pyarrow.lib',
    'google', 'google.protobuf',
    'requests', 'urllib3', 'charset_normalizer', 'certifi', 'idna',
    'tenacity',
    'toml',
    'tornado', 'tornado.web', 'tornado.websocket', 'tornado.ioloop',
    'tornado.httpserver', 'tornado.routing',
    'typing_extensions',
    'watchdog', 'watchdog.observers', 'watchdog.events',

    # Bandit
    'bandit', 'bandit.core', 'bandit.core.issue', 'bandit.core.manager',
    'bandit.core.node_visitor', 'bandit.core.meta_ast',
    'bandit.core.test_properties', 'bandit.core.tester',
    'bandit.cli', 'bandit.cli.main',
    'bandit.formatters', 'bandit.formatters.json', 'bandit.formatters.text',
    'bandit.plugins',
    'stevedore', 'stevedore.driver', 'stevedore.extension',
    'stevedore.named', 'stevedore._cache',
    'yaml',

    # x_ray_core
    'x_ray_core',

    # Common missing imports in frozen apps
    'pkg_resources', 'packaging', 'packaging.version',
    'packaging.specifiers', 'packaging.requirements',
    'email', 'email.mime', 'email.mime.text', 'email.mime.multipart',
    'json', 'decimal', 'fractions',
    'markupsafe', 'jinja2',
]

# ─── Analysis ─────────────────────────────────────────────────────────────────

a = Analysis(
    ['x_ray_web.py'],
    pathex=[str(PROJECT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'PyQt5', 'PyQt6', 'wx',
        'matplotlib',        # Not needed
        'scipy',
        'torch', 'tensorflow',
        'IPython', 'notebook', 'jupyter',
        'test', 'tests',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='x_ray_web',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,      # Console so user can see server output / Ctrl+C
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='x_ray_web',
)
