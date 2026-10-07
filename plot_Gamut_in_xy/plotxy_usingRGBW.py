import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import colour
from colour.plotting import plot_chromaticity_diagram_CIE1931
from pathlib import Path

# ==========================================
# 1. 直接输入 R、G、B 原色及白点的 xy 坐标
# 这里是Apple Wide Gamut
# ==========================================
# # 红羽 (Red Primary)
# r_x, r_y = 0.725, 0.301

# # 绿羽 (Green Primary)
# g_x, g_y = 0.221, 0.814

# # 蓝羽 (Blue Primary)
# b_x, b_y = 0.068, -0.076

# # 白点 (White Point - D65)
# wp_x, wp_y = 0.3127, 0.3290

# CINITY WIDE GAMUT = ZRGB

r_x, r_y = 0.680538, 0.247445
g_x, g_y = 0.280588, 1.015126
b_x, b_y = 0.081251, -0.095965
wp_x, wp_y = 0.32168, 0.33767

# ==========================================
# 2. 整合数据并闭合三角形
# ==========================================
x_coords = [r_x, g_x, b_x]
y_coords = [r_y, g_y, b_y]

primaries_x = np.array([r_x, g_x, b_x, r_x])
primaries_y = np.array([r_y, g_y, b_y, r_y])

# 3. 初始化 CIE 1931 色度图背景
figure, axes = plot_chromaticity_diagram_CIE1931(
    show=False,
    show_spectral_locus=False,
    show_chromaticity_diagram_colours=True
)

# 4. 降低马蹄形背景色彩的不透明度至 30%
for img in axes.images:
    img.set_alpha(0.3)
for collection in axes.collections:
    collection.set_alpha(0.3)

# 5. 绘制色域三角形与核心点 (极细红线 linewidth=0.5, 散点 s=4)
axes.plot(primaries_x, primaries_y, color='#ED4B35', linewidth=0.5, linestyle='-', zorder=4)
axes.scatter(x_coords, y_coords, color='#ED4B35', s=4, zorder=5)
axes.scatter(wp_x, wp_y, color='#ED4B35', s=4, zorder=5)

# 6. 刻度与网格步进设置
# 主刻度：步长 0.2 (控制数字显示与网格)
axes.xaxis.set_major_locator(ticker.MultipleLocator(0.2))
axes.yaxis.set_major_locator(ticker.MultipleLocator(0.2))

# 次刻度：步长 0.05 (只显示小刻度线)
axes.minorticks_on()
axes.xaxis.set_minor_locator(ticker.MultipleLocator(0.05))
axes.yaxis.set_minor_locator(ticker.MultipleLocator(0.05))

# 7. 样式设置（参考 fig-chromaticity-plot-output-1.png）
axes.set_facecolor('#F5F5F5')
figure.patch.set_facecolor('white')

# 网格线：只绑定主刻度 (0.2 步长) 虚线
axes.grid(True, which='major', color='#D5D5D5', linestyle='--', linewidth=0.5, zorder=1)
axes.grid(False, which='minor')

# 刻度线细节调整
axes.tick_params(which='both', direction='out', color='black')
axes.tick_params(which='major', length=6, width=0.8)
axes.tick_params(which='minor', length=3.5, width=0.5)

# 轴范围与标签
axes.set_xlabel('CIE x', fontsize=12, labelpad=8)
axes.set_ylabel('CIE y', fontsize=12, labelpad=8)
axes.set_xlim([-0.1, 0.9])
axes.set_ylim([-0.18, 1.1])

# 移除多余元素
axes.set_title('')
if axes.get_legend():
    axes.get_legend().remove()

for spine in axes.spines.values():
    spine.set_color('#333333')
    spine.set_linewidth(0.8)

axes.set_aspect('equal')

# 8. 创建输出目录并保存 PNG
pic_dir = Path(__file__).parent.parent / 'pic'
pic_dir.mkdir(exist_ok=True)

output_path = pic_dir / 'chromaticity-plot.png'
figure.savefig(
    output_path,
    dpi=144,
    bbox_inches='tight',
    facecolor='white',
    edgecolor='none'
)
print(f"✓ Saved: {output_path}")

# 9. 渲染输出
plt.show()