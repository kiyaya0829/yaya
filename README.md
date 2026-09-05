# Yaya 交易日记

一个轻量的 Windows 桌面交易日记。手动记录每笔买卖和决策理由，数据仅保存在本机。

## 第一版 · 0.1.0

- 添加、修改、删除交易记录；删除前确认。
- 股票代码、买入/卖出、币种、成交价、数量、日期、交易理由和复盘笔记。
- 按代码或笔记搜索，日期倒序展示，支持小数数量。
- SQLite 本机存储；价格和数量以精确十进制文本保存。
- 一键备份数据库。

没有实时行情、券商连接、自动交易或盈亏计算。不同币种不合并统计。

## Windows 使用

在 GitHub Actions 的成功构建中下载 `YayaJournal-Windows-x64`，解压后双击 `YayaJournal.exe`。不需要安装 Python。当前构建为测试版本，尚未签名。

点击列表中的记录即可修改，点“保存记录”提交修改；点“新建 / 清空”开始另一条记录。切换记录或清空表单会放弃尚未保存的输入，请先保存。

数据默认保存在 `%LOCALAPPDATA%\YayaJournal\journal.sqlite3`，与程序分开；替换程序不会清除记录。数据和备份未加密，请将它们保存在自己的电脑上。

点“备份记录”另存数据库。恢复时先关闭程序，备份当前数据库，再将需要恢复的备份复制到上述位置并命名为 `journal.sqlite3`。不要将个人数据库提交到 GitHub。

## 从源码运行

需要 Python 3.12（含 Tkinter）。运行时无第三方依赖。

```powershell
python app.py
python -m unittest discover -v
python app.py --smoke-test
```

可用 `python app.py --data-dir ./local-data` 指定数据目录。

## Windows 打包

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name YayaJournal app.py
```

产物：`dist/YayaJournal.exe`。必须在 Windows 上构建 Windows 可执行文件。
打包方式参考 [PyInstaller 官方文档](https://pyinstaller.org/en/stable/usage.html)。

## 自动构建与待确认发布

`.github/workflows/build.yml` 在 main / feature 分支提交、PR 或手动运行时，测试存储与界面、打包 Windows x64 程序、验证程序启动，并上传 exe、说明和 SHA-256 校验文件，保留 30 天。参见 [GitHub artifact 文档](https://github.com/actions/upload-artifact)。

工作流只有 contents:read 权限，不会创建 tag 或 Release。

发布前：

1. 确认 Actions 全部通过，下载并在 Windows 上试用新增、编辑、删除、重启与备份。
2. 确定版本号、对应提交、发布说明与构建产物。
3. 获得仓库所有者明确确认后，才创建版本 tag 和 GitHub Release 并附上产物。

首版拟用 `v0.1.0`，目前未创建 tag 或 Release。
