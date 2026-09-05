# Yaya 交易日记 · 0.3.0

Windows 桌面交易日记：记录交易、复盘、备份，并在打开软件时后台更新美股持仓收盘行情。

## 使用

从 GitHub Actions 下载 YayaJournal-Windows-x64，解压后双击 YayaJournal.exe。无需安装 Python。程序未签名。

1. 在「行情设置」中打开申请链接，获取个人 Alpha Vantage API Key，在软件内填写并保存。无需将密钥发给任何人。
2. 新增记录选择市场 US、币种 USD，填写美股代码（例如 AAPL）、买入数量和价格。
3. 打开「美股持仓 / 收盘行情」查看当前持仓。打开软件时自动检查更新，也可点击「更新收盘价」。网络访问在后台进行。
4. 交易页包含全部历史记录，支持编辑、删除、搜索和数据库备份。

首次升级：旧记录全部保留，市场标记为「待确认」，不会按币种猜测市场。请按时间顺序先确认买入，再确认卖出为 US。其他市场记录继续保留，但不获取行情。

## 行情与持仓规则

- 同一 US 代码累计买入减卖出；部分卖出继续更新，清仓停止更新，再次买入恢复。
- 卖出不能超过此前记录的买入，同日按录入顺序检查。修改、删除也检查此规则。仅支持普通多头，暂不处理拆股、转仓、做空。
- 所有持仓必须在同一个已完成交易日取得收盘价，整批才发布。
- 一批不齐，显示上一批完整报价；首次或新增股票导致无完整批次时，所有价格显示「准备中」。已取得报价继续缓存，不重复请求。
- 按 XNYS 交易日历判断美国节假日、提前收市、夏令时；数据商可能晚于收盘更新，尚未取得目标日期时不冒充最新报价。临时休市可能需要日历库更新。
- 请求失败或目标日尚未更新，同一股票同一目标日一小时内不重复请求；可稍后再打开或手动更新。软件关闭时不采集。
- 本机使用保守的滚动 24 小时最多 25 次请求限制，失败请求也计入。真实账号额度还可能被其他软件使用。
- 超过 25 只持仓时提示免费方案不足，不自动删除记录或优先更新一部分股票。
- 报价为 Alpha Vantage 未复权日收盘价、USD，显示美国交易日期，不覆盖实际成交价。盈亏总览严格按所选估值日期计算，详见下方说明。

## 本机数据与密钥

默认数据库：%LOCALAPPDATA%\YayaJournal\journal.sqlite3。替换程序不会删除记录。数据库及备份未加密，包含交易和缓存行情。

个人 API Key 由 Windows DPAPI 按当前 Windows 用户保护，独立存放为 api-key.dpapi，不包含在日记备份中。移到其他电脑后重新填写。行情设置留空保存可移除；已保存密钥不回显。开发时可使用 ALPHAVANTAGE_API_KEY 环境变量，其优先级高于保存值。

仅向 Alpha Vantage 请求持仓代码及 API Key，不发送买卖数量、成交价或笔记。不要将个人密钥或数据库提交到仓库。

「备份记录」导出 SQLite 数据库。恢复前关闭程序，先备份当前数据库，再将要恢复的备份复制至上述目录并改名 journal.sqlite3。

切换记录或关闭前请先保存，未保存的表单输入不会自动保存。

## 源码运行与验证

需要 Python 3.12（含 Tkinter）。

```powershell
python -m pip install -r requirements.txt
python app.py
python -m unittest discover -v
python app.py --smoke-test
```

可用 `python app.py --data-dir ./local-data` 指定数据目录。

测试使用模拟响应，不消耗个人行情额度；覆盖旧数据库升级、持仓、整批发布、额度、重启缓存及交易日历。界面和打包自检还验证持仓窗口与 Windows 密钥保护。真实账号连接需配置个人 Key 后验证。

## 构建和发布

```powershell
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all exchange_calendars --collect-all tzdata --name YayaJournal app.py
```

GitHub Actions 在开发分支、main 提交、PR 或手动触发后测试、构建并验证 Windows exe，上传程序、说明、SHA-256 校验文件，保留 30 天。仅 contents:read 权限，不创建 tag 或 Release。

发布前先下载试用，确认版本、对应提交、构建产物和发布说明。只有得到仓库所有者明确确认后才创建 tag 或 Release。

参考：[Alpha Vantage 日线](https://www.alphavantage.co/documentation/#daily)、[免费额度与申请](https://www.alphavantage.co/support/)、[交易日历](https://pypi.org/project/exchange-calendars/4.11.2/)。

## 0.3.0 盈亏和导出

主界面的「盈亏总览」按估值日计算 US/USD 普通多头的当日持仓、平均成本、剩余成本、收盘估值、已实现盈亏、浮动盈亏及合计。默认最近已发布报价日期，无已发布日期时默认今天；可在总览中改日期。所有盈亏均截至同一天，之后的交易不计入该日汇总。

手续费默认为 0，可在交易表单修改；买入费用计入成本，卖出费用扣收入，采用移动加权平均成本。旧记录费用默认为 0，请补全。缺少估值日价格时，相应浮动及总计显示「待补齐」，已实现盈亏仍展示。此功能不处理拆股、分红、转仓、做空或税务。

「导出 Excel」生成综合汇总、交易明细、计算说明三页；交易明细保留被排除的记录并标记原因。在总览中可导出选定日期。工作簿为与页面一致的数值快照，修改单元格不会重算；Excel 数值精度约15位有效数字。用户笔记按文本导出，不执行公式。

