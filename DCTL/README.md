# Waveform Picture — 藏在示波器里的画面

一个"好玩"的 DaVinci Resolve DCTL：**画面本身变成灰度瀑布条纹，但在示波器（Waveform / Luma）上看，显示的却是原始画面。**

| 左：原图 | 中：DCTL 输出（时间线上看到的） | 右：示波器里看到的 |
|---|---|---|
| 正常彩色画面 | 灰度"瀑布"条纹 | 原始画面重现 |

预览图见 `preview/preview.png`（由验证脚本生成）。

---

## 原理

波形监视器画的是**每一列像素的亮度直方图**：

```
D(x, h) = count{ y : L(x, y) ≈ h }
```

- 横坐标 `x` = 图像的列（和画面横坐标一一对应，天然对齐）
- 纵坐标 `h` = 信号电平（亮度），**不是**画面的纵坐标
- 某点的亮度 = 该列中落在该电平的像素**个数**

所以要让示波器上显示原画面，需要让输出图像满足：

```
第 x 列中，值 ≈ h_j 的像素个数  ∝  原画面 (x, 第 j 行) 的亮度
```

即把原画面第 `j` 行的亮度，编码成"输出图像第 x 列里有多少像素取电平 `h_j`"。亮的地方点密、暗的地方点疏——示波器上就呈现出一张点阵密度图，正是原画面。

### 实现（逆变换采样 / Inverse CDF Sampling）

对每个输出像素 `(x, y)`：

1. **Pass 1** — 用 `_tex2D` 沿本列采样 `bins` 个等距行，得到亮度剖面 `w[j]`（`j=0` 对应画面最上一行），做 exposure / gamma / invert 处理
2. **取 u** — 采样位置 `u = y / H`（像素的行位置，自上而下）
3. **Pass 2** — 对 `w[]` 的累积分布 CDF 做**逆查找**（含线性插值），得到剖面位置 `pos ∈ [0,1)`
4. **输出** — `level = 1 - pos`，使电平 1.0（示波器顶部）对应画面最上一行 → **画面正立**；输出灰度 `(level, level, level)`

因为逆 CDF 采样使 `pos` 的分布密度正比于 `w[j]`，最终每个电平的像素数就正比于原画面对应行的亮度——这正是所需的等式。

---

## 为什么用顺排（Waterfall）

`u` 直接取像素的行位置，因此**同一列内输出电平随行严格单调**，每个电平对应画面的一行，示波器上呈现为清晰的"瀑布"条纹。相比随机排布：

- **最锐利** — 无噪声，隐藏画面与原始画面逐行对应
- **逐帧稳定** — 不含任何时间项与伪随机数，静帧不闪烁
- **无摩尔纹** — 不做等距随机分层，因此也不会与示波器电平格产生干涉条纹

代价是直接观看时画面是规整的条纹（而非随机雪花），条纹本身可被辨识，所以画面"藏得没那么深"。若要更彻底的隐身效果，可以在输出上加一层时间抖动，但会牺牲示波器上的清晰度。

---

## 安装

把 `Waveform Picture GHYC.dctl` 复制到 Resolve 的 LUT 目录：

- **Windows** — `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT\`
- **macOS** — `/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT/`
- **Linux** — `/home/resolve/LUT/`

然后在 Color 页面右键 LUT 面板 → **Refresh**（或重启 Resolve）。

## 使用

1. Color 页面新建一个 Serial Node
2. Effects → ResolveFX Color → **DCTL**，拖到该节点
3. 在 DCTL List 下拉里选 **Waveform Picture GHYC**
4. **打开示波器**：右上角 Scopes 按钮 → 选择 **Waveform**，模式设为 **Luma**（或按 Y 通道显示）
5. 此时时间线画面是灰度条纹瀑布，而示波器里显示的是原画面 🎉

> ⚠️ 直接看输出画面只会看到条纹。**必须配合示波器观看**，这就是这个效果的全部乐趣所在。

### 建议
- 示波器窗口拉到最大，效果最清楚
- 原素材对比度高、主体明确时效果最好（人像、剪影、Logo）
- 若示波器显示偏暗/偏平，调 `Exposure` 与 `Dot Contrast`

---

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| **Histogram Bins** | 128 | 隐藏画面的**垂直分辨率**（电平轴方向）。越大越细腻，但每像素采样数线性增加。128–192 是画质/速度的甜点，上限 256 |
| **Row Samples** | 2 | 每个 bin 内的行采样数（盒式平均）。1 = 点采样（快，但细密横向纹理会混叠）；2–4 = 抗混叠，隐藏画面更干净 |
| **Dot Contrast** | 1.8 | 对亮度剖面加 gamma。调大 → 暗部更疏、亮部更密，隐藏画面对比度更高（默认 1.8 比传统 1.3 更能撑开暗部细节） |
| **Exposure** | 1.0 | 剖面整体增益。原片偏暗时调大 |
| **Output Gamma** | 1.0 | 对输出电平加 gamma，改变画面在**电平轴上的分布**（隐藏画面会被纵向拉伸/压缩） |
| **Reveal Original** | 0.0 | 与原图混合。从 0 拉到 1，画面从条纹渐变回原片，示波器上的隐藏画面同步"融化"——很适合做转场 |
| **Invert Picture** | 0 | 反相隐藏画面（亮暗互换） |
| **Flip Vertical** | 0 | 隐藏画面上下翻转 |
| **Flip Horizontal** | 0 | 隐藏画面左右镜像 |
| **Scope Graticule** | 0 | 叠加仿示波器刻度线（会作为信号输出，因此示波器上也会出现） |

---

## 本地验证（无需 Resolve）

`verify_waveform_picture.py` 在 numpy 中**完整复现** DCTL 算法，并模拟波形监视器渲染，可以在打开 Resolve 之前先确认效果：

```bash
# 默认：自动使用系统壁纸，参数与 DCTL 默认值一致
python verify_waveform_picture.py

# 指定图片与参数
python verify_waveform_picture.py --input myshot.png --bins 192 --gamma 1.6
```

输出到 `preview/`：

- `encoded.png` — DCTL 节点会产出的画面
- `waveform.png` — 模拟示波器视图（**隐藏画面在这里**）
- `preview.png` — 三联对比图

命令行参数与 DCTL 的 UI 参数一一对应：`--bins --rowsub --gamma --exposure --outgamma --invert --flipx --flipy --mix`。

脚本使用 float64，而 GPU 是 float32 —— 涉及数值精度的改动仍需在 Resolve 里实机确认。

依赖：`numpy`、`pillow`。

---

## 性能

每像素做 `bins × Row Samples` 次纹理采样（Pass 1）+ 最多 `bins` 次 CDF 遍历（Pass 2）。默认 128 bins × 2 = 256 次 `_tex2D`，与同目录的 `MTF Curve GHYC.dctl`（约 336 次采样）同量级，现代 GPU 上 1080p 实时无压力。

4K + 256 bins × 4 samples = 1024 次采样/像素会明显变慢，建议**先降 bins 调参、渲染时再拉高**。若只想提速，先把 `Row Samples` 降到 1（画质损失小于降 bins）。

## 已知特性

- **全黑列**：整列亮度为 0（或 invert 后为 0）时无法构造分布，此时均匀铺满该列，避免示波器上出现一根刺眼的亮线
- **逐帧稳定**：只依赖坐标，不含时间项，所以静帧不会闪烁；视频逐帧变化仅来自素材本身
- **色度示波器无意义**：输出是纯灰度，请使用 Waveform 的 **Luma** 模式（Parade 下 R/G/B 三条曲线完全相同）
