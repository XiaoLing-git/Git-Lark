# git-lark

[简体中文](README.zh-CN.md) | English

`git-lark` is a small Git extension that sends commit notifications through configurable Feishu/Lark bots.
It works as both `git-lark ...` and `git lark ...` once the executable is available on `PATH`.

## Features

- Multiple named bot profiles.
- Feishu custom webhook bots, with optional signature secret.
- Feishu enterprise app bots, targeting an `open_id`, `chat_id`, `user_id`, or `union_id`.
- Per-repository profile selection stored in `.git/config`.
- Safe `post-commit` installation that chains an existing hook and restores it on uninstall.
- Commit metadata, full commit message, and changed-file list.
- Duplicate suppression per profile and commit SHA.
- Notification failures never invalidate a completed Git commit.
- Windows DPAPI encryption for secrets belonging to the current Windows user.
- Single-file Windows executable builds through PyInstaller.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Create a bot profile

Webhook bot:

```powershell
git lark profile add-webhook development
```

Enterprise application bot:

```powershell
git lark profile add-app release `
  --app-id cli_xxxxxxxxx `
  --recipient ou_xxxxxxxxx `
  --receive-id-type open_id
```

Secrets are requested interactively when their corresponding command-line option is omitted. Avoid putting secrets
directly in shell history. Profile metadata is stored under `%APPDATA%\git-lark\config.json`; secret values are kept
separately in `%APPDATA%\git-lark\secrets.json` and encrypted with Windows DPAPI.

## Enable a repository

```powershell
cd path\to\repository
git lark init --profile development
git lark test
git lark status
```

`init` installs a managed `post-commit` wrapper. If a hook already exists, it is moved to
`post-commit.git-lark-backup` and called before `git-lark`. To remove the integration and restore the old hook:

```powershell
git lark uninstall
```

Useful commands:

```powershell
git lark profile list
git lark profile show development
git lark use release
git lark test --dry-run
git lark doctor
git lark config-path
```

## Build and install the EXE

```powershell
.\build.ps1
.\install.ps1
```

The result is `dist\git-lark.exe`. The installer copies it to
`%LOCALAPPDATA%\Programs\git-lark` and adds that directory to the user `PATH`.

## Configuration and safety

Project configuration is local to the repository:

```text
git-lark.enabled=true
git-lark.profile=development
```

The hook performs a synchronous request with a short timeout. If delivery fails, the commit still succeeds and the
error is written below the repository Git metadata directory in `git-lark/notify.log`.

On non-Windows systems this initial version stores secret values with an explicit `plain:` marker and restrictive file
permissions. Do not copy that file or commit it. A future cross-platform release should use the operating system's
native credential service.

## License

This project is licensed under GPL-3.0-only. See [LICENSE](LICENSE) for details.

