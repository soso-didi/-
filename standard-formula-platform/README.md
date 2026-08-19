# 规范公式计算平台

JTS 144-1-2010 的本地公式计算平台。使用人员可按章节勾选已发布公式并计算；管理员维护草稿、验算和发布版本。OCR 资料只能作为后台录入草稿，计算内核从不执行 OCR 文本。

## 当前实现

- FastAPI + SQLite 后端，安全 AST 计算器支持代数式、条件、查表和线性插值。
- 本地浏览器界面提供登录、公式选择、参数合并、计算过程、历史记录及管理员草稿录入。
- 首次启动将从相邻的 `MooringForceDemo-Complete` 迁移同一 PDF 与第 30 页的 OCR 元数据，不会重新 OCR。
- 已内置并发布 JTS 144-1-2010 第 10.2.1 条的 `N、Nx、Ny、Nz` 四个审核公式，其他条款由管理员按审核流程录入。

## 开发运行

本目录已包含 Demo 的 Python 3.12 便携运行时和 React 的生产构建产物：

```powershell
cd standard-formula-platform
..\MooringForceDemo-Complete\runtime\python\python.exe -m uvicorn backend.app:app --port 8010
```

访问 `http://127.0.0.1:8010`。默认演示账户：`admin/admin123` 和 `user/user123`；实际部署前必须更换。

## 检查

```powershell
..\MooringForceDemo-Complete\runtime\python\python.exe -m unittest discover -s tests -v
```

## Windows 完整包

双击 `0-启动规范公式计算平台.cmd` 即可启动。`Backup-Data.ps1` 创建数据库和规范资料备份，`Restore-Data.ps1 -ArchivePath <备份.zip>` 恢复备份。运行 `Build-Portable.ps1` 生成可复制到其他 Windows 电脑的 ZIP；Inno Setup 安装包脚本默认目标为 `D:\规范公式计算平台`，见 `packaging/installer.iss`。
