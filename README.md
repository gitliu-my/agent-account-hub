# Agent Account Hub

Agent Account Hub 是一个本地多账号切换工具，用来管理不同 CLI 的认证快照，并在不同账号之间快速切换。

当前支持：

- Codex：管理 `~/.codex/auth.json` 快照
- Claude Code：管理 macOS Keychain 里的 `Claude Code-credentials` 凭据快照

它只处理当前 provider 真正使用的认证载体和 Hub 自己保存的快照，不会改你的 session、history、config 或其他数据目录。

## Features

- Web 控制台，优先展示当前账号和已保存账号列表
- macOS 菜单栏 app，适合快速切换
- 支持在 Codex 和 Claude Code 之间切换 provider
- 保存当前账号、覆盖已有账号、切换、删除
- 同一账号的当前认证如果刷新了 token，会自动同步回已保存快照
- 支持打包成 macOS `.app`

## Install

### macOS App

推荐直接用 Homebrew：

```bash
brew install --cask gitliu-my/tap/codex-account-hub
```

如果你不想用 Homebrew，也可以直接从 GitHub Release 安装 `.app`：

```bash
tmpdir="$(mktemp -d)" && \
gh release download --repo gitliu-my/codex-account-hub --pattern "Agent.Account.Hub.zip" --dir "$tmpdir" && \
mkdir -p "$HOME/Applications" && \
ditto -x -k "$tmpdir/Agent.Account.Hub.zip" "$tmpdir/unpacked" && \
ditto "$tmpdir/unpacked/Agent Account Hub.app" "$HOME/Applications/Agent Account Hub.app"
```

如果仓库是公开的，也可以用安装脚本：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/gitliu-my/codex-account-hub/main/scripts/install-app.sh)
```

### CLI / Dev

如果你要跑 CLI 或本地开发：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e .
```

## Usage

### App

安装后直接打开：

```bash
open "$HOME/Applications/Agent Account Hub.app"
```

如果你装到了系统应用目录，就打开：

```bash
open "/Applications/Agent Account Hub.app"
```

### Web

```bash
python3 -m codex_account_hub serve
```

默认地址：

```text
http://127.0.0.1:8766
```

### Tray

```bash
python3 -m codex_account_hub tray
```

### CLI

```bash
python3 -m codex_account_hub current
python3 -m codex_account_hub list
python3 -m codex_account_hub capture-new
python3 -m codex_account_hub capture account-1
python3 -m codex_account_hub switch account-1
python3 -m codex_account_hub clear account-1
```

切到 Claude Code：

```bash
PYTHONPATH=src python3 -m codex_account_hub --provider claude-code current
PYTHONPATH=src python3 -m codex_account_hub --provider claude-code list
PYTHONPATH=src python3 -m codex_account_hub --provider claude-code capture-new
PYTHONPATH=src python3 -m codex_account_hub --provider claude-code switch account-1
```

说明：

- Codex 当前凭据路径是 `~/.codex/auth.json`
- Claude Code 当前凭据主存储在 macOS Keychain，服务名是 `Claude Code-credentials`
- Claude Code 的已保存快照会写到 Hub 自己的数据目录里，不会直接覆盖你的其他 Claude 配置目录

## Development

运行测试：

```bash
python3 -m unittest tests.test_core tests.test_providers tests.test_tray
```

打包 app：

```bash
python3 -m pip install py2app
python3 setup.py py2app
```

GitHub Actions 会在 push `v*` tag 时自动构建并发布 `Agent.Account.Hub.zip`。
