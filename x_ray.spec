# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for X-Ray Standalone .exe
==========================================
Builds a self-contained Windows executable that includes:
  - Full X-Ray scanner (AST smells, duplicates, reporting, grade)
  - Ruff linter (bundled ruff.exe)
  - Bandit security scanner (bundled Python package)
  - x_ray_core Rust acceleration (.pyd)
  - Hardware detection
"""

import os
import sys
import shutil
from pathlib import Path

# Project root
PROJECT = Path(SPECPATH)

# Find tools
ruff_path = shutil.which("ruff") or str(PROJECT / ".venv" / "Scripts" / "ruff.exe")
bandit_path = shutil.which("bandit") or str(PROJECT / ".venv" / "Scripts" / "bandit.exe")
x_ray_core_pyd = str(PROJECT / ".venv" / "Lib" / "site-packages" / "x_ray_core" / "x_ray_core.cp313-win_amd64.pyd")

# Fallback x_ray_core location
if not os.path.isfile(x_ray_core_pyd):
    x_ray_core_pyd = str(PROJECT / "x_ray_core.pyd")

print(f"  [spec] ruff.exe:      {ruff_path}")
print(f"  [spec] bandit.exe:    {bandit_path}")
print(f"  [spec] x_ray_core:    {x_ray_core_pyd}")

# --- Binaries to bundle alongside the exe ---
binaries = []
if os.path.isfile(ruff_path):
    binaries.append((ruff_path, '.'))          # ruff.exe → output root
if os.path.isfile(bandit_path):
    binaries.append((bandit_path, '.'))        # bandit.exe → output root
if os.path.isfile(x_ray_core_pyd):
    binaries.append((x_ray_core_pyd, '.'))     # x_ray_core.pyd → output root

# --- Data files ---
datas = []
# Include the x_ray_core package (in case it has __init__.py etc.)
xray_core_pkg = PROJECT / ".venv" / "Lib" / "site-packages" / "x_ray_core"
if xray_core_pkg.is_dir():
    datas.append((str(xray_core_pkg), 'x_ray_core'))

# --- Hidden imports ---
hidden_imports = [
    'Core',
    'Core.types',
    'Core.config',
    'Core.utils',
    'Core.inference',
    'Core.ast_helpers',
    'Analysis',
    'Analysis.ast_utils',
    'Analysis.smells',
    'Analysis.duplicates',
    'Analysis.similarity',
    'Analysis.lint',
    'Analysis.security',
    'Analysis.reporting',
    'Analysis.rust_advisor',
    'Analysis.auto_rustify',
    'Analysis.test_gen',
    'Analysis.tracer',
    'Analysis.smart_graph',
    'Analysis.library_advisor',
    'Lang',
    'Lang.python_ast',
    'Lang.tokenizer',
    # Bandit and its plugins (so security analysis works standalone)
    'bandit',
    'bandit.core',
    'bandit.core.issue',
    'bandit.core.node_visitor',
    'bandit.core.meta_ast',
    'bandit.core.test_properties',
    'bandit.core.tester',
    'bandit.core.manager',
    'bandit.cli',
    'bandit.cli.main',
    'bandit.formatters',
    'bandit.formatters.json',
    'bandit.formatters.text',
    'bandit.plugins',
    # stevedore (bandit plugin loader)
    'stevedore',
    'stevedore.driver',
    'stevedore.extension',
    'stevedore.named',
    'stevedore._cache',
    # YAML (bandit dependency)
    'yaml',
    # x_ray_core
    'x_ray_core',
]

a = Analysis(
    ['x_ray_exe.py'],
    pathex=[str(PROJECT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'streamlit',      # Not needed for CLI
        'matplotlib',
        'PyQt5',
        'PyQt6',
        'wx',
        'PIL',
        'numpy',
        'pandas',
        'scipy',
        'torch',
        'tensorflow',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],                # Empty for onedir
    exclude_binaries=True,
    name='x_ray',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='x_ray',
)
