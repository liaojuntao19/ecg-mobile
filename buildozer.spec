# buildozer.spec — Kivy App 打包配置（供 GitHub Actions 云打包使用）
# 完整配置参考：https://buildozer.readthedocs.io/en/latest/specifications.html

[app]
# 应用名（手机桌面显示的名字）
title = 心电ECG

# 包名（唯一标识，Android 要求）
package.name = ecg
package.domain = org.ecg

# 源文件
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,txt

# 版本
version = 0.1
version.regex = __version__ = ['"]([^'"]+)['"]
version.filename = %(source.dir)s/main.py

# 入口
main.py = main.py

# Python 版本（buildozer 用 3.8-3.11）
python3.version = 3.11

# ---------- 依赖 ----------
# 打包 ecg_filter.py 需要 scipy + numpy
requirements = python3,kivy==2.3.1,numpy,scipy,bleak

# ---------- 权限（手机蓝牙必需） ----------
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_SCAN,BLUETOOTH_CONNECT,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION

# Android API 级别（BLE 权限需要较新 API）
android.api = 33
android.minapi = 24

# ---------- 图标/启动（可选，先用默认） ----------
# icon.filename = %(source.dir)s/icon.png
# presplash.filename = %(source.dir)s/presplash.png

# 横屏（波形更适合横屏）
orientation = landscape

# ---------- 架构（通用） ----------
android.archs = arm64-v8a

# 日志
log_level = 2

[buildozer]
log_level = 2
warn_on_root = 1
