[app]
title = 心电ECG
package.name = ecg
package.domain = org.ecg
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,txt
version = 0.1
main.py = main.py
python3.version = 3.11
requirements = python3,kivy==2.3.1,numpy,scipy,bleak
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_SCAN,BLUETOOTH_CONNECT,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION
android.api = 33
android.minapi = 24
orientation = landscape
android.archs = arm64-v8a
log_level = 2

[buildozer]
log_level = 2
warn_on_root = 1
