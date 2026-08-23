# -*- coding: utf-8 -*-
"""
心电滤波算法模块 v2.0
====================
包含：
  1. 老师滤波链（保留）：直流去除 → 50Hz陷波 → 卡尔曼平滑 → mV换算
  2. 专业带通滤波（新增，默认）：scipy 巴特沃斯 0.5~40Hz（医学标准）
     —— 支持逐样本流式处理（sosfilt + zi 状态）
  3. 平滑度调节：滤波强度可调（低通截止频率 / 卡尔曼强度）

接口统一：
    filt = EcgFilter(mode="bandpass", smoothness=0.5)
    mv = filt.process(adc_value)     # 输入 int，输出 float mV
    filt.reset()                     # 复位

用法（与 pc-ui.py 兼容，接口不变）：
    from ecg_filter import EcgFilter
"""

import math
import numpy as np
from scipy import signal

# ---------- 老师代码里的 mV 换算系数（ADC 值 × 0.3223 ≈ 毫伏） ----------
MV_SCALE = 0.3223


class DcRemover:
    """直流偏置去除（一阶高通滤波器）"""

    def __init__(self, alpha=0.99):
        self.alpha = alpha
        self.prev_in = 0.0
        self.prev_out = 0.0

    def process(self, x):
        y = self.alpha * (self.prev_out + x - self.prev_in)
        self.prev_in = x
        self.prev_out = y
        return y

    def reset(self):
        self.prev_in = 0.0
        self.prev_out = 0.0


class Notch50Hz:
    """50Hz 陷波器（IIR 双二阶，直接 II 型，老师系数）"""

    def __init__(self):
        self.b0 = 0.991196234823306321359837056661490350962
        self.b1 = -0.000000000000000121386529630327029776745
        self.b2 = 0.991196234823306321359837056661490350962
        self.a1 = -0.000000000000000121386529630327029776745
        self.a2 = 0.982392469646612642719674113322980701923
        self.w1 = 0.0
        self.w2 = 0.0

    def process(self, x):
        w = x - self.a1 * self.w1 - self.a2 * self.w2
        y = self.b0 * w + self.b1 * self.w1 + self.b2 * self.w2
        self.w2 = self.w1
        self.w1 = w
        return y

    def reset(self):
        self.w1 = 0.0
        self.w2 = 0.0


class KalmanSmooth:
    """卡尔曼平滑滤波器（老师代码 KS_Filter 原样移植）"""

    def __init__(self):
        self.error_measure = 1.0
        self.error_estimate = 30.0
        self.q = 0.8
        self.last_estimate = 0.0

    def process(self, mea):
        gain = self.error_estimate / (self.error_estimate + self.error_measure)
        current = self.last_estimate + gain * (mea - self.last_estimate)
        self.error_estimate = (1.0 - gain) * self.error_estimate + abs(self.last_estimate - current) * self.q
        self.last_estimate = current
        return current

    def reset(self):
        self.error_measure = 1.0
        self.error_estimate = 30.0
        self.q = 0.8
        self.last_estimate = 0.0


class BandpassFilter:
    """专业心电带通滤波器（scipy 巴特沃斯）
    0.5~40Hz 医学标准带宽：滤掉基线漂移(<0.5Hz)和肌电噪声(>40Hz)
    支持逐样本流式处理：sosfilt + zi 状态变量
    smoothness 调节：0~1，映射到低通截止频率 30Hz~12Hz
    （smoothness 越大越平滑，但 R 波高频分量保留越少）"""

    def __init__(self, sample_rate=200, smoothness=0.5):
        self.fs = sample_rate
        self._rebuild(smoothness)
        # 滑动平均平滑（对齐回放 signal_smooth 效果，消除实时毛糙）
        self.smooth_win = 9          # 9 点滑动平均（200Hz ≈ 45ms）
        self.smooth_buf = [0.0] * self.smooth_win

    def _rebuild(self, smoothness):
        """按平滑度重建滤波器（smoothness 0~1）
        高通 0.05Hz（医学标准，减少相位失真/T波压扁）
        低通 25~40Hz（smoothness=0→40Hz保真，=1→25Hz平滑）"""
        smoothness = max(0.0, min(1.0, smoothness))
        # 低通截止：smoothness=0 → 40Hz（保真），=1 → 25Hz（平滑，减噪声）
        low_cut = 40.0 - 15.0 * smoothness
        high_cut = 0.05                     # 高通 0.05Hz（医学标准，原0.5过高致S波过深）
        nyq = self.fs / 2.0
        if low_cut >= nyq:
            low_cut = nyq - 1.0
        sos = signal.butter(4, [high_cut / nyq, low_cut / nyq],
                            btype='bandpass', output='sos')
        self.sos = sos
        # 流式状态：每个二阶节 2 个状态
        self.zi = signal.sosfilt_zi(sos)
        # 起始状态为零（从无历史开始）
        self.zi = np.zeros_like(self.zi)

    def process(self, x):
        """输入一个样本，返回滤波后样本（带通 + 滑动平均平滑）"""
        # 1. 带通滤波（流式）
        y, self.zi = signal.sosfilt(self.sos, [float(x)], zi=self.zi)
        # 2. 滑动平均平滑（消除实时毛糙，对齐回放效果）
        self.smooth_buf.pop(0)
        self.smooth_buf.append(y[0])
        return sum(self.smooth_buf) / self.smooth_win

    def set_smoothness(self, smoothness):
        """运行中调节平滑度（重建滤波器，状态清零）"""
        self._rebuild(smoothness)

    def reset(self):
        self.zi = np.zeros_like(self.zi)
        self.smooth_buf = [0.0] * self.smooth_win


class NeuroFilter:
    """NeuroKit2 标准滤波（业界成熟方案）
    用 ecg_clean 处理，消除自写滤波的过冲/失真问题。
    流式实现：维护滑动窗口（约1秒），每来一个样本滑动一位，
    用 ecg_clean 处理整段，返回窗口最后一点的滤波值。

    幅度补偿（自适应）：ecg_clean 会衰减信号（实测增益~0.09），
    为与老师算法（增益~0.88）幅度一致，用"输入/输出峰峰值比"
    自适应补偿——窗口内输入峰峰值 / 输出峰峰值 = 补偿系数，
    只还原被滤波压掉的幅度，不改变波形形态。"""

    def __init__(self, sample_rate=200, window_seconds=1.0):
        self.fs = sample_rate
        self.win_len = int(sample_rate * window_seconds)
        self.buf = []          # 原始 ADC 缓冲

    def process(self, adc_value):
        """输入 ADC 原始值，返回滤波后 mV 值（自适应幅度补偿）"""
        import neurokit2 as nk
        self.buf.append(float(adc_value))
        if len(self.buf) > self.win_len:
            self.buf.pop(0)
        # 窗口未满时返回 0（等待积攒）
        if len(self.buf) < max(50, self.win_len // 2):
            return 0.0
        try:
            arr = np.array(self.buf)
            cleaned = nk.ecg_clean(arr, sampling_rate=self.fs)
            # 自适应补偿：输入/输出 峰峰值比（限制在合理范围）
            in_pp = float(np.max(arr) - np.min(arr))
            out_pp = float(np.max(cleaned) - np.min(cleaned))
            if in_pp > 0 and out_pp > 0:
                gain = in_pp / out_pp
                gain = max(0.5, min(gain, 20.0))   # 限制范围防爆
            else:
                gain = 1.0
            # 返回窗口最后一点 × 补偿 × mV换算
            return float(cleaned[-1]) * gain * MV_SCALE
        except Exception:
            return 0.0

    def reset(self):
        self.buf = []


class EcgFilter:
    """完整滤波链（接口统一，模式可选）
    mode: "nk"（NeuroKit2标准，推荐）/ "bandpass"（自写带通）
          / "teacher"（老师算法）/ "none"（原始）
    smoothness: 0~1，平滑度（bandpass 模式下有效）"""

    def __init__(self, mode="nk", smoothness=0.5, sample_rate=200):
        self.mode = mode
        self.sample_rate = sample_rate
        self.dc = DcRemover()
        self.notch = Notch50Hz()
        self.kalman = KalmanSmooth()
        self.bp = BandpassFilter(sample_rate, smoothness)
        self.nf = NeuroFilter(sample_rate)

    def process(self, adc_value):
        """输入 ADC 原始值 (int)，返回滤波后的毫伏值 (float)"""
        x = float(adc_value)
        if self.mode == "nk":
            return self.nf.process(x)
        elif self.mode == "bandpass":
            y = self.bp.process(x)
            return y * MV_SCALE
        elif self.mode == "notch":
            # 简单方案：只 50Hz 陷波（原厂方案），保留信号形态
            y = self.notch.process(x)
            return y * MV_SCALE
        elif self.mode == "teacher":
            y = self.dc.process(x)
            y = self.notch.process(y)
            y = self.kalman.process(y)
            return y * MV_SCALE
        else:
            return self.dc.process(x) * MV_SCALE

    def set_mode(self, mode):
        self.mode = mode
        self.reset()

    def set_smoothness(self, smoothness):
        """运行中调平滑度（带通模式重建滤波器）"""
        self.bp.set_smoothness(smoothness)

    def reset(self):
        self.dc.reset()
        self.notch.reset()
        self.kalman.reset()
        self.bp.reset()
        self.nf.reset()


if __name__ == "__main__":
    # 自测：对比三种模式的滤波效果
    import random
    print("=== 滤波算法自测（模拟 900 直流偏置 + 1Hz 心电 + 50Hz 工频 + 噪声）===")
    for mode in ["teacher", "bandpass", "none"]:
        f = EcgFilter(mode=mode)
        vals = []
        for i in range(800):
            t = i / 200.0
            s = (900 + 100 * math.sin(2 * math.pi * 1.0 * t)
                 + 50 * math.sin(2 * math.pi * 50 * t)
                 + random.uniform(-10, 10))
            vals.append(f.process(s))
        mid = vals[300:]
        amp = (max(mid) - min(mid)) / 2
        print(f"  [{mode:10s}] 均值={sum(mid)/len(mid):7.2f} mV  "
              f"波动幅度={amp:7.2f} mV  (越小越平滑)")
