# -*- coding: utf-8 -*-
"""
心电 ECG 手机版（Kivy）· v2.0 - DeepSeek 风格
================================
手机端 App：接收 ESP32 BLE 心电数据 → 复用 ecg_filter.py 算法 → 绘制心电图
DeepSeek 蓝白风格 + 中文字体支持

运行（电脑）：
  py -3.11 ecg_mobile.py
"""
import sys
import math
import threading
import time

import kivy
kivy.require("2.3.0")
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle
from kivy.core.window import Window
from kivy.core.text import LabelBase

# ---------- 中文字体（兼容电脑/手机） ----------
CN_FONT = None
# 电脑：微软雅黑
for _fp in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyh.ttf"]:
    import os
    if os.path.exists(_fp):
        try:
            LabelBase.register(name="CN", fn_regular=_fp)
            CN_FONT = "CN"
            break
        except Exception:
            pass
# 手机：Android 系统字体（由 buildozer 指定，见 buildozer.spec）
if CN_FONT is None:
    CN_FONT = "Roboto"   # 兜底（手机有 Roboto，中文可能显示不全，后续可打包中文字体）

# ---------- DeepSeek 风格配色 ----------
DS_BLUE = (0.30, 0.42, 1.0, 1)        # #4D6BFE
DS_BLUE_DARK = (0.23, 0.33, 0.84, 1)  # 深蓝
DS_BG = (0.96, 0.97, 0.98, 1)         # 浅灰白背景
DS_WHITE = (1, 1, 1, 1)
DS_RED = (0.91, 0.30, 0.24, 1)        # 停止红
DS_TEXT = (0.2, 0.2, 0.25, 1)         # 深灰文字
DS_GRAY = (0.85, 0.87, 0.9, 1)        # 浅灰

# 复用 PC 端算法（与 main.py 同目录）
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ecg_filter import EcgFilter

DEV_NAME = "ECG-S3"
SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
CHAR_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
FRAME_HEADER = b"\xaa\x55"


class FrameParser:
    def __init__(self):
        self._rx = bytearray()

    def feed(self, data: bytes):
        import struct
        samples = []
        self._rx += data
        while len(self._rx) >= 5:
            if self._rx[:2] != FRAME_HEADER:
                self._rx.pop(0)
                continue
            L = int.from_bytes(self._rx[2:4], "little")
            total = 4 + L + 1
            if len(self._rx) < total:
                break
            if (sum(self._rx[:4 + L]) & 0xFF) != self._rx[4 + L]:
                self._rx.pop(0)
                continue
            for i in range(4, 4 + L, 2):
                samples.append(struct.unpack("<h", self._rx[i:i+2])[0])
            del self._rx[:total]
        return samples


class StyledButton(Button):
    """DeepSeek 风格按钮"""
    def __init__(self, text="", primary=False, **kwargs):
        super().__init__(**kwargs)
        self.text = text
        self.font_name = CN_FONT
        self.font_size = 22
        self.bold = True
        self.color = DS_WHITE if primary else DS_BLUE
        self.background_normal = ""
        self.background_color = DS_BLUE if primary else DS_WHITE
        self.border = (0, 0, 0, 0)
        self.size_hint = (1, 1)


class ECGWidget(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.sample_rate = 200
        self.display_seconds = 7.5
        self.max_points = int(self.sample_rate * self.display_seconds)
        self.data = []
        self.raw = []
        self.filt = EcgFilter(mode="notch")
        self.parser = FrameParser()
        self.running = False
        self.thread = None
        self.sim_idx = 0
        self.src = "sim"

        # 背景
        with self.canvas.before:
            Color(*DS_BG)
            self.bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *a: setattr(self.bg, "pos", self.pos))
        self.bind(size=lambda *a: setattr(self.bg, "size", self.size))

        # 标题
        self.add_widget(Label(
            text="心电 ECG 上位机", font_name=CN_FONT, font_size=26,
            bold=True, color=DS_BLUE, size_hint=(1, 0.08)))

        # 波形
        self.plot = PlotWidget(size_hint=(1, 0.6))
        self.add_widget(self.plot)

        # 心率
        self.lbl_hr = Label(
            text="心率: -- BPM", font_name=CN_FONT, font_size=30,
            bold=True, color=DS_RED, size_hint=(1, 0.08))
        self.add_widget(self.lbl_hr)

        # 控制区
        bar = BoxLayout(size_hint=(1, 0.16), spacing=12, padding=(12, 8))
        self.btn_sim = StyledButton("模拟数据", primary=True)
        self.btn_ble = StyledButton("BLE连接")
        self.btn_start = StyledButton("开始", primary=True)
        bar.add_widget(self.btn_sim)
        bar.add_widget(self.btn_ble)
        bar.add_widget(self.btn_start)
        self.add_widget(bar)

        self.btn_sim.bind(on_press=lambda x: self.set_src("sim"))
        self.btn_ble.bind(on_press=lambda x: self.set_src("ble"))
        self.btn_start.bind(on_press=self.toggle_start)
        # 高亮选中
        self.btn_sim.background_color = DS_BLUE
        self.btn_ble.background_color = DS_GRAY
        self.btn_ble.color = DS_TEXT

        Clock.schedule_interval(self.update_plot, 1.0 / 30.0)

    def set_src(self, src):
        self.src = src
        self.stop_source()
        if src == "sim":
            self.btn_sim.background_color = DS_BLUE
            self.btn_sim.color = DS_WHITE
            self.btn_ble.background_color = DS_GRAY
            self.btn_ble.color = DS_TEXT
        else:
            self.btn_ble.background_color = DS_BLUE
            self.btn_ble.color = DS_WHITE
            self.btn_sim.background_color = DS_GRAY
            self.btn_sim.color = DS_TEXT

    def toggle_start(self, btn):
        if self.running:
            self.stop_source()
            self.btn_start.text = "开始"
            self.btn_start.background_color = DS_BLUE
        else:
            self.start_source()

    def start_source(self):
        self.running = True
        self.data.clear()
        self.raw.clear()
        self.thread = threading.Thread(target=self.source_loop, daemon=True)
        self.thread.start()
        self.btn_start.text = "停止"
        self.btn_start.background_color = DS_RED

    def stop_source(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
            self.thread = None
        self.btn_start.text = "开始"
        self.btn_start.background_color = DS_BLUE

    def source_loop(self):
        if self.src == "sim":
            while self.running:
                frame = []
                for _ in range(10):
                    i = self.sim_idx % self.sample_rate
                    v = 900.0
                    if 20 <= i < 45: v += 60 * math.sin(math.pi*(i-20)/25)
                    if 55 <= i < 66: v += 1800 * math.exp(-((i-58)/3.0)**2)
                    if 95 <= i < 140: v += 280 * math.sin(math.pi*(i-95)/45)
                    frame.append(int(v))
                    self.sim_idx += 1
                self.on_samples(frame)
                time.sleep(0.05)
        else:
            self.ble_loop()

    def ble_loop(self):
        import asyncio
        from bleak import BleakClient, BleakScanner
        def on_notify(_c, data):
            samples = self.parser.feed(bytes(data))
            if samples:
                self.on_samples(samples)
        while self.running:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                found = None
                def cb(device, adv):
                    nonlocal found
                    name = adv.local_name or device.name or ""
                    if "ECG" in name and found is None:
                        found = device
                scanner = BleakScanner(detection_callback=cb, scanning_mode="active")
                loop.run_until_complete(scanner.start())
                end = loop.time() + 8.0
                while found is None and loop.time() < end:
                    loop.run_until_complete(asyncio.sleep(0.5))
                loop.run_until_complete(scanner.stop())
                if not found:
                    loop.close()
                    time.sleep(3)
                    continue
                client = BleakClient(found.address)
                loop.run_until_complete(client.connect())
                loop.run_until_complete(client.start_notify(CHAR_TX_UUID, on_notify))
                while self.running and client.is_connected:
                    loop.run_until_complete(asyncio.sleep(0.5))
                loop.close()
            except Exception:
                try:
                    loop.close()
                except Exception:
                    pass
                time.sleep(3)

    def on_samples(self, samples):
        for s in samples:
            mv = self.filt.process(s)
            self.data.append(mv)
            self.raw.append(s)
        if len(self.data) > self.max_points:
            del self.data[:-self.max_points]
            del self.raw[:-self.max_points]

    def update_plot(self, dt):
        if self.data:
            self.plot.set_data(self.data)
            hr = self.calc_hr()
            if hr:
                self.lbl_hr.text = f"心率: {hr:.0f} BPM"

    def calc_hr(self):
        if len(self.data) < self.sample_rate * 2:
            return None
        window = self.data[-self.sample_rate * 3:]
        if not window:
            return None
        thr = (max(window) + min(window)) / 2
        peaks = 0
        for i in range(1, len(window) - 1):
            if window[i] > thr and window[i] > window[i-1] and window[i] > window[i+1]:
                peaks += 1
        if peaks > 0:
            return peaks * 20


class PlotWidget(BoxLayout):
    """波形绘制：白底 + 蓝线 + XY轴刻度（像 PC 端）"""
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.points = []
        self.display_seconds = 7.5

        # 上轴（时间刻度）
        top = BoxLayout(size_hint=(1, 0.06))
        self.x_labels = []
        for i in range(6):
            lbl = Label(text="", font_name=CN_FONT, font_size=11,
                        color=(0.45, 0.45, 0.5, 1))
            self.x_labels.append(lbl)
            top.add_widget(lbl)
        self.add_widget(top)

        # 波形主体（带左边 y 刻度）
        body = BoxLayout(orientation="horizontal", size_hint=(1, 0.88))
        ycol = BoxLayout(orientation="vertical", size_hint=(None, 1), width=70)
        self.y_labels = []
        for i in range(5):
            lbl = Label(text="", font_name=CN_FONT, font_size=11,
                        color=(0.45, 0.45, 0.5, 1))
            self.y_labels.append(lbl)
            ycol.add_widget(lbl)
        body.add_widget(ycol)
        self.plot_area = PlotArea(size_hint=(1, 1))
        body.add_widget(self.plot_area)
        self.add_widget(body)

        # 下轴（占位，x 刻度已在顶部，底部留白）
        self.add_widget(Label(text="", size_hint=(1, 0.06)))

        # 更新刻度
        for i, lbl in enumerate(self.x_labels):
            t = i * (self.display_seconds / 5)
            lbl.text = f"{t:.1f}s"
        for i, lbl in enumerate(self.y_labels):
            frac = 1.0 - i / 4.0   # 上到下
            val = (frac - 0.5) * 4
            lbl.text = f"{val:.1f}"

    def set_data(self, data):
        self.plot_area.set_data(data)


class PlotArea(Label):
    """纯画布区域：网格 + 波形线"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.points = []
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self.bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *a: setattr(self.bg, "pos", self.pos))
        self.bind(size=lambda *a: setattr(self.bg, "size", self.size))

    def set_data(self, data):
        self.points = list(data)
        self.canvas.clear()
        with self.canvas:
            # 网格（浅灰）
            Color(0.92, 0.93, 0.95, 1)
            for i in range(1, 5):
                y = self.height * i / 5
                Line(points=[(0, y), (self.width, y)], width=1)
            for i in range(1, 6):
                x = self.width * i / 6
                Line(points=[(x, 0), (x, self.height)], width=1)
            # 中线
            Color(0.85, 0.87, 0.9, 1)
            Line(points=[(0, self.height/2), (self.width, self.height/2)], width=2)
            # 波形（DeepSeek 蓝）
            Color(0.30, 0.42, 1.0, 1)
            if len(self.points) > 1:
                w, h = self.width, self.height
                mid = h / 2
                scale = h / 4
                pts = []
                n = len(self.points)
                for i, v in enumerate(self.points):
                    x = i / (n - 1) * w
                    y = mid + v * scale / 1000.0
                    pts.append((x, y))
                Line(points=pts, width=2)


class ECGApp(App):
    def build(self):
        # 手机横屏比例预览（波形更宽，像 PC 端效果）
        Window.size = (900, 420)
        Window.clearcolor = DS_BG
        return ECGWidget()


if __name__ == "__main__":
    ECGApp().run()
