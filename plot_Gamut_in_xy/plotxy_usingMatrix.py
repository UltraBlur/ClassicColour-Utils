import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import colour
from colour.plotting import plot_chromaticity_diagram_CIE1931

# # 1. 填入转置（Transpose）后的 RGB to XYZ 矩阵
# RGB_XYZ = np.array([
#     [ 0.736478,  0.130740,  0.083239],
#     [ 0.275070,  0.828018, -0.103088],
#     [-0.124225, -0.087160,  1.300443]
# ])

# # 1. 填入转置（Transpose）后的 F-GamutC RGB to XYZ 矩阵
# RGB_XYZ = np.array([
#     [0.636958048301291,  0.1446169035862084,   0.16888097516417208],
#     [0.2627002120112669, 0.6779980715188711,   0.05930171646986195],
#     [4.994106574466073e-17, 0.028072693049087445, 1.0609850577107909]
# ])

# 1.F-Gamut RGB to XYZ 矩阵，好像就是Rec.2020
# RGB_XYZ = np.array([
#     [0.636958048301291,  0.1446169035862084,   0.16888097516417208],
#     [0.2627002120112669, 0.6779980715188711,   0.05930171646986195],
#     [4.994106574466073e-17, 0.028072693049087445, 1.0609850577107909]
# ])

# # 1. 填入原始 S-Log2 矩阵并加 .T 自动转置
# RGB_XYZ = np.array([
#     [0.7185461625168931,   0.1273538637756839,   0.10674997361319535],
#     [0.2756067472590483,   0.7777682389570769,  -0.05337498621612528],
#     [-0.009843098238302875, 0.004548351896868362, 1.0141247452018174]
# ])

# # S-Gamut Daylight
# RGB_XYZ = np.array([
#     [0.834865827285226,    0.013840441479989713,  0.1039398057977495],
#     [0.3536961933652236,   0.7072157160678367,   -0.06091190943306034],
#     [0.057862616207303624, -0.11612247074827806,  1.0670850387844006]
# ])

# 1. 填入转置（Transpose）后的 S-Gamut2 Tungsten RGB to XYZ 矩阵
RGB_XYZ = np.array([
    [0.9630588414611801,   -0.12979720872309236,  0.11938444176927096],
    [0.41711481940026685,   0.6567071120173268,   -0.07382193141759362],
    [0.06060684054003592,  -0.10191003866691933,  1.0501283825131695]
])

# 2. 计算转置矩阵的三原色 xy 坐标
columns_sum = RGB_XYZ.sum(axis=0)
x_coords = RGB_XYZ[0] / columns_sum
y_coords = RGB_XYZ[1] / columns_sum

# 闭合三角形 (R -> G -> B -> R)
primaries_x = np.append(x_coords, x_coords[0])
primaries_y = np.append(y_coords, y_coords[0])
wp_x, wp_y = 0.3127, 0.3290

# 3. 初始化 CIE 1931 色度图
figure, axes = plot_chromaticity_diagram_CIE1931(
    standalone=False,
    show_spectral_locus=False, 
    show_chromaticity_diagram_colours=True
)

# 4. 【核心修改：降低马蹄形背景色彩的不透明度至 30%】
for img in axes.images:
    img.set_alpha(0.3)
for collection in axes.collections:
    collection.set_alpha(0.3)

# 5. 绘制新色域三角形 (极细红线 linewidth=0.5, 散点 s=4)
axes.plot(primaries_x, primaries_y, color='#ED4B35', linewidth=0.5, linestyle='-', zorder=4)
axes.scatter(x_coords, y_coords, color='#ED4B35', s=4, zorder=5)
axes.scatter(wp_x, wp_y, color='#ED4B35', s=4, zorder=5)

# 6. 刻度与网格步进设置 (数字与网格0.2，刻度0.04)
# 主刻度：步长 0.2 (控制数字显示与网格)
axes.xaxis.set_major_locator(ticker.MultipleLocator(0.2))
axes.yaxis.set_major_locator(ticker.MultipleLocator(0.2))

# 次刻度：步长 0.04 (只显示小刻度线)
axes.minorticks_on()
axes.xaxis.set_minor_locator(ticker.MultipleLocator(0.04))
axes.yaxis.set_minor_locator(ticker.MultipleLocator(0.04))

# 7. 极简高阶视觉美化
axes.set_facecolor('#F7F7F8')
figure.patch.set_facecolor('#F7F7F8')

# 网格线：只绑定主刻度 (0.2 步长)
axes.grid(True, which='major', color='#E4E4E7', linestyle='--', linewidth=0.5, zorder=1)
axes.grid(False, which='minor') 

# 刻度线细节调整
axes.tick_params(which='both', direction='out', color='#A1A1AA')
axes.tick_params(which='major', length=6, width=0.8) 
axes.tick_params(which='minor', length=3, width=0.5) 

# 轴范围与标签
axes.set_xlabel('CIE x', fontsize=12, labelpad=8)
axes.set_ylabel('CIE y', fontsize=12, labelpad=8)
axes.set_xlim([-0.1, 0.9])
axes.set_ylim([-0.1, 1.0])

# 移除多余元素
axes.set_title('')
if axes.get_legend():
    axes.get_legend().remove()

for spine in axes.spines.values():
    spine.set_color('#71717A')
    spine.set_linewidth(0.8)

axes.set_aspect('equal')

# 8. 渲染输出
plt.show()