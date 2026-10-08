# 开发、打包与验证

在项目根目录执行下列命令。


建议 Windows 10/11、Python 3.11–3.13。

```powershell
python -m pip install -r requirements.txt
python main.py
```

RapidOCR 首次准备模型可能需要网络，模型就绪后识别可离线运行。Windows OCR 是备用引擎，受系统语言包影响。本地复核默认开启，每次最多处理 6 个可疑区域，并限制额外处理预算。

```powershell
python -m pip install pyinstaller
python package.py --iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

需安装 Inno Setup 编译器，可用 `--iscc` 指定路径或 `ISCC` 环境变量。只生成便携包可用 `python package.py --portable-only`。构建结果位于 `dist/v2.0.0`，打包脚本先对标准运行库和便携模式分别进行 EXE 自检，再生成 ZIP、安装器与 SHA256 校验文件。目录式运行库位于 `dist/ScreenshotTranslator`，保留 `_internal` 目录。

## 验证

```powershell
python -m unittest discover -s tests -v
python tests/windows_overlay_hit_check.py
```

回归覆盖配置迁移、写入失败保护、安装与便携路径、多语言实际请求参数、缺失 OCR 语言包提示、界面保存，以及原有截图、原位擦字、贴图、分组、排版、缓存和帮助检查。另有 Windows 真实桌面像素与原生窗口命中检查，确认框选后保持清晰且不会把鼠标交给下层应用。接口测试使用模拟请求，不消耗 API 额度；不代表全部语种的真实在线翻译质量或 OCR 精度。
