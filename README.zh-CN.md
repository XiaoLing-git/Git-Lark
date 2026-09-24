# git-lark

简体中文 | [English](README.md)

`git-lark` 是一个轻量的 Git 扩展，可在代码提交完成后，通过可配置的飞书/Lark 机器人发送通知。
只要将可执行文件加入 `PATH`，既可以使用 `git-lark ...`，也可以像原生 Git 子命令一样使用
`git lark ...`。

## 功能特性

- 支持多个具名机器人 Profile，不同项目可以使用不同机器人。
- 支持飞书自定义 Webhook 机器人，可选签名密钥。
- 支持飞书企业自建应用机器人，可向 `open_id`、`chat_id`、`user_id` 或 `union_id` 发送消息。
- 每个仓库选择的 Profile 保存在仓库本地 `.git/config`，不会提交到代码仓库。
- 安全安装 `post-commit` 钩子：已有钩子会被备份并串联执行，卸载时自动恢复。
- 通知包含仓库、分支、Commit、作者、时间、完整提交信息和变更文件列表。
- 按 Profile 和 Commit SHA 去重，避免同一提交被重复发送。
- 通知失败不会导致已经完成的 Git 提交失败。
- Windows 使用当前用户的 DPAPI 加密机器人密钥。
- 支持通过 PyInstaller 构建单文件 Windows EXE。

## 快速开始

### 1. 安装 EXE

在项目目录执行：

```powershell
.\install.ps1
```

安装脚本会把 `dist\git-lark.exe` 复制到：

```text
%LOCALAPPDATA%\Programs\git-lark
```

并将该目录加入当前用户的 `PATH`。安装完成后需要重新打开终端或 IDE。

### 2. 创建机器人 Profile

使用飞书自定义 Webhook 机器人：

```powershell
git lark profile add-webhook development
```

命令会以隐藏输入方式询问 Webhook URL，避免密钥出现在终端历史中。

如果机器人启用了签名校验：

```powershell
git lark profile add-webhook development --signed
```

使用飞书企业自建应用机器人：

```powershell
git lark profile add-app release `
  --app-id cli_xxxxxxxxx `
  --recipient ou_xxxxxxxxx `
  --receive-id-type open_id
```

未通过参数提供的 `app_secret` 会由命令交互式询问。

### 3. 为仓库启用通知

进入需要接入通知的 Git 仓库：

```powershell
cd C:\path\to\repository
git lark init --profile development
git lark test
git lark status
```

之后该仓库每次完成 Git 提交，都会使用 `development` Profile 发送通知。

## Profile 管理

查看所有 Profile：

```powershell
git lark profile list
```

查看不包含密钥的 Profile 信息：

```powershell
git lark profile show development
```

为当前仓库切换机器人：

```powershell
git lark use release
```

删除 Profile 及其密钥：

```powershell
git lark profile remove development
```

## 常用命令

```powershell
# 查看最终通知文本，但不发送
git lark notify --dry-run

# 手动发送当前 HEAD 的通知
git lark notify --force

# 发送测试消息
git lark test

# 检查钩子、Profile 和密钥状态
git lark doctor

# 查看用户配置目录
git lark config-path

# 查看当前仓库接入状态
git lark status

# 卸载当前仓库钩子并恢复原钩子
git lark uninstall
```

## 钩子兼容机制

`git lark init` 会安装一个由 git-lark 管理的 `post-commit` 包装器。如果仓库已经存在
`post-commit` 钩子，原文件会被移动为：

```text
post-commit.git-lark-backup
```

每次提交时先执行原钩子，再执行 git-lark。运行 `git lark uninstall` 后，包装器会被删除，
原钩子会恢复到原位置。

## 配置与密钥

用户级 Profile 元数据保存在：

```text
%APPDATA%\git-lark\config.json
```

敏感值单独保存在：

```text
%APPDATA%\git-lark\secrets.json
```

Windows 上的敏感值使用 DPAPI 加密，只能由保存密钥的 Windows 用户解密。请勿复制或提交
`secrets.json`。

项目选择的 Profile 保存在仓库自己的 `.git/config`：

```text
git-lark.enabled=true
git-lark.profile=development
```

这些配置不会进入工作区，也不会被 Git 提交。

## 通知内容与失败处理

通知默认包含：

- 仓库名称和当前分支。
- Commit SHA、作者及提交时间。
- 完整 Commit Message。
- 新增、修改、删除和重命名的文件列表。

文件较多时，消息会自动拆分。每个 Profile 会记录最后一次成功发送的 Commit SHA，同一提交不会
重复发送。网络或飞书接口异常不会影响 Git 提交，错误会记录在仓库 Git 元数据目录下：

```text
.git\git-lark\notify.log
```

## 源码开发

要求 Python 3.10 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
```

## 构建单文件 EXE

```powershell
.\build.ps1
```

构建结果：

```text
dist\git-lark.exe
```

构建脚本会安装项目的 `build` 可选依赖并调用 PyInstaller。生成的 EXE 不要求目标项目安装
Python、Poetry 或飞书 SDK。

## 非 Windows 平台说明

首版在非 Windows 系统中使用带有 `plain:` 标记的受限权限文件保存密钥，而不是系统凭据服务。
请勿复制或提交该文件。后续跨平台版本应接入各操作系统的原生凭据存储。

## 许可证

本项目采用 GPL-3.0-only 许可证，详情参见 [LICENSE](LICENSE)。
