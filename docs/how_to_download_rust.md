# How to Install and Validate Rust (Windows)

**Note**: This file is for internal development use only.

## 1. Automated Installation (PowerShell)
Run the following commands in PowerShell to download and install the Rust toolchain silently:

```powershell
# 1. Download rustup-init.exe
Invoke-WebRequest -Uri "https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe" -OutFile "rustup-init.exe"

# 2. Install (Silent / Default)
.\rustup-init.exe -y

# 3. Clean up
Remove-Item "rustup-init.exe"
```

## 2. Verification
After installation, **restart your terminal** (or VS Code) to reload the `PATH`. Then check:

```powershell
rustc --version
cargo --version
```

## 3. Troubleshooting
If `rustc` is still not found, add the cargo bin directory to your PATH manually:
`$env:USERPROFILE\.cargo\bin`
