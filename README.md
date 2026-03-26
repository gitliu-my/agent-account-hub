# Codex Account Hub

`Codex Account Hub` 是一个本地账号切换工具，用来管理多个 Codex `auth.json` 快照，并在需要时把某一份快照写回 `~/.codex/auth.json`。

它的目标很单一:

- 看清当前登录的是哪个账号
- 把当前登录保存为新的本地账号记录
- 用当前登录覆盖某条已保存账号
- 在多条已保存账号之间快速切换
- 在网页控制台和 macOS 菜单栏里完成这些操作

这里的“账号”只是本地保存的 `auth.json` 快照，不是服务端概念，也不限制数量。

## 它不会修改什么

这个项目不会碰下面这些路径:

- `~/.codex/config.toml`
- `~/.codex/sessions/`
- `~/.codex/history.jsonl`
- `~/.codex/logs_*.sqlite`
- `~/.codex/state_*.sqlite`
- `~/.codex/memories/`
- `~/.codex/hooks.json`

它只在两类地方写数据:

- 当前生效认证: `~/.codex/auth.json`
- Hub 自己管理的快照目录: `data/` 或 macOS App Support 目录

## 功能概览

- Web 控制台优先展示当前活动认证和已保存账号列表
- 支持“保存当前为新账号”“覆盖已有账号”“切换”“删除”
- 菜单栏里直接按邮箱或更可识别的身份展示账号
- 自动检测当前 `~/.codex/auth.json` 是否已经匹配某条已保存账号
- 打包成 macOS `.app` 后，数据默认保存到 `~/Library/Application Support/Codex Account Hub`

## 环境要求

- Python 3.11+
- macOS 仅在菜单栏模式和 `.app` 打包时需要

## 安装

建议在虚拟环境里安装:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e .
```

如果你需要打包成 macOS `.app`:

```bash
python3 -m pip install py2app
```

## 使用

### Web 控制台

启动本地控制台:

```bash
python3 -m codex_account_hub serve
```

默认地址:

```text
http://127.0.0.1:8766
```

第一屏会直接显示:

- 当前活动认证
- 当前认证是否已保存
- 已保存账号列表
- 新增、覆盖、切换、删除操作

### macOS 菜单栏

启动菜单栏模式:

```bash
python3 -m codex_account_hub tray
```

常用参数:

```bash
python3 -m codex_account_hub tray --dashboard-port 8766 --refresh-seconds 5
```

说明:

- `tray` 只支持 macOS
- 打开网页控制台时会自动启动本地 HTTP 服务
- 菜单栏会定时刷新状态
- 打包后的 `.app` 是 `LSUIElement=true`，默认不在 Dock 常驻

### CLI

查看当前认证:

```bash
python3 -m codex_account_hub current
```

查看已保存账号:

```bash
python3 -m codex_account_hub list
```

把当前登录保存成一条新账号:

```bash
python3 -m codex_account_hub capture-new
```

用当前登录覆盖某条已保存账号:

```bash
python3 -m codex_account_hub capture account-1
```

切换到某条已保存账号:

```bash
python3 -m codex_account_hub switch account-1
```

从文件导入一条账号快照:

```bash
python3 -m codex_account_hub import-file account-2 /path/to/auth.json
```

重命名一条账号:

```bash
python3 -m codex_account_hub rename account-2 "工作账号"
```

删除一条已保存账号:

```bash
python3 -m codex_account_hub clear account-2
```

所有主要命令都支持直接输出 JSON 结果，便于后续脚本集成。

## 存储

源码模式下默认使用项目目录里的本地数据目录:

- `data/state.json`
- `data/accounts/<account-id>/auth.json`

打包后的 macOS `.app` 默认改用:

- `~/Library/Application Support/Codex Account Hub/state.json`
- `~/Library/Application Support/Codex Account Hub/accounts/<account-id>/auth.json`

你也可以通过环境变量覆盖数据目录:

- `CODEX_ACCOUNT_HUB_DATA_ROOT`
- `CODEX_ACCOUNT_HUB_LEGACY_DATA_ROOT`

如果旧版本数据还在项目目录 `data/` 下，`.app` 首次启动时会自动迁移可识别的历史快照。

## 开发

运行单元测试:

```bash
python3 -m unittest tests.test_core tests.test_tray
```

语法检查:

```bash
python3 -m py_compile src/codex_account_hub/*.py tests/*.py
```

打包:

```bash
python3 setup.py py2app
```

## 仓库约定

这个仓库默认不提交下面这些内容:

- `data/` 里的本地账号快照和状态文件
- `dist/` 和 `build/` 里的打包产物
- `.venv/`、`__pycache__/`、`*.egg-info/` 等本地或编译产物

也就是说，推到远端的是源码、脚本、测试和文档，不包含用户数据。
