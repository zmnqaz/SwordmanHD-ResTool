#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""从 libretro slang-shaders 生成 game/engine/render/hq/xbrz6_alpha.gdshader 的 xBRZ 判定部分 (机械转换, 避免手抄出错)。

  gen_hq_shaders.py <slang-shaders 检出目录>   # git clone https://github.com/libretro/slang-shaders (只需 edge-smoothing/)

转换: 取 edge-smoothing/xbrz/shaders/6xbrz.slang 片元主体; 像素改 vec4 (带 alpha), 等值比较 v[i]==v[j] 改成含 alpha 的
eq(); 去掉原版重复粘贴的一段; `(X) == false` 改成 `!(X)`。文件头 (alpha 感知距离、取样、收紧、合成) 在本脚本里。
hqx 着色器 (hqx.gdshader) 是手写的单 pass 版, 查表图 hq{2,3,4}x.png 直接取自 edge-smoothing/hqx/resources/。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "game", "engine", "render", "hq", "xbrz6_alpha.gdshader")

HEAD = r'''// SPDX-License-Identifier: GPL-3.0-only
// 6 倍 xBRZ 只取透明通道 + 收紧, 与 hq 链颜色合成最终贴图 (= 当初离线 6 倍流水线的做法: hq 链颜色 + tighten(xbrz alpha))。
// 本文件由 tools/assets/gen_hq_shaders.py 生成, 判定部分机械转换自 libretro slang-shaders edge-smoothing/xbrz/shaders/6xbrz.slang
// (Hyllian 的 xBR 框架 MIT; xBRZ 算法 Zenju, GPL-3.0 —— 见 hq/README.md 许可说明)。
// 与原版的差别 (对齐离线用的 C++ xBRZ 1.8 ARGB 模式, 实测透明通道与 hd6x 逐像素相同):
//   像素带 alpha, 距离按 ColorDistanceARGB (alpha 加权 + alpha 差), 等值比较含 alpha; 图外按全透明;
//   混合对 alpha 线性 (= C++ alphaGrad 的 alpha 结果), 颜色不用 (颜色取 hq 链)。
shader_type canvas_item;
render_mode blend_disabled, unshaded;

uniform sampler2D orig : filter_nearest;     // 1 倍原图 RGBA
uniform sampler2D color6 : filter_nearest;   // hq 链 6 倍颜色

#define BLEND_NONE 0
#define BLEND_NORMAL 1
#define BLEND_DOMINANT 2
#define LUMINANCE_WEIGHT 1.0
#define EQUAL_COLOR_TOLERANCE 30.0/255.0
#define STEEP_DIRECTION_THRESHOLD 2.2
#define DOMINANT_DIRECTION_THRESHOLD 3.6

const float one_sixth = 1.0 / 6.0;
const float two_sixth = 2.0 / 6.0;
const float four_sixth = 4.0 / 6.0;
const float five_sixth = 5.0 / 6.0;

float DistYCbCr(vec4 pixA, vec4 pixB) {
	vec3 w = vec3(0.2627, 0.6780, 0.0593);
	float scaleB = 0.5 / (1.0 - w.b);
	float scaleR = 0.5 / (1.0 - w.r);
	vec3 diff = pixA.rgb - pixB.rgb;
	float Y = dot(diff, w);
	float Cb = scaleB * (diff.b - Y);
	float Cr = scaleR * (diff.r - Y);
	float d = sqrt(((LUMINANCE_WEIGHT * Y) * (LUMINANCE_WEIGHT * Y)) + (Cb * Cb) + (Cr * Cr));
	// C++ xBRZ ColorDistanceARGB: 透明度低的一方按 alpha 缩小颜色差, 再加上 alpha 差
	return pixA.a < pixB.a ? pixA.a * d + (pixB.a - pixA.a) : pixB.a * d + (pixA.a - pixB.a);
}

bool IsPixEqual(vec4 pixA, vec4 pixB) {
	return DistYCbCr(pixA, pixB) < EQUAL_COLOR_TOLERANCE;
}

bool IsBlendingNeeded(ivec4 blend) {
	return any(notEqual(blend, ivec4(BLEND_NONE)));
}

bool eq(vec4 a, vec4 b) {
	return all(equal(a, b));
}

// 图外按全透明 (C++ xBRZ 1.8 ARGB 的 OobReaderTransparent; libretro 原版是夹到边缘)
vec4 px(ivec2 p, ivec2 sz) {
	return any(lessThan(p, ivec2(0))) || any(greaterThanEqual(p, sz)) ? vec4(0.0) : texelFetch(orig, p, 0);
}

void fragment() {
	ivec2 sz = textureSize(orig, 0);
	vec2 sp = UV * vec2(sz);
	ivec2 p = ivec2(floor(sp));
	vec2 f = fract(sp);
	//   Input Pixel Mapping:  20|21|22|23|24
	//                         19|06|07|08|09
	//                         18|05|00|01|10
	//                         17|04|03|02|11
	//                         16|15|14|13|12
	vec4 src[25];
	src[21] = px(p + ivec2(-1, -2), sz);
	src[22] = px(p + ivec2(0, -2), sz);
	src[23] = px(p + ivec2(1, -2), sz);
	src[6] = px(p + ivec2(-1, -1), sz);
	src[7] = px(p + ivec2(0, -1), sz);
	src[8] = px(p + ivec2(1, -1), sz);
	src[5] = px(p + ivec2(-1, 0), sz);
	src[0] = px(p, sz);
	src[1] = px(p + ivec2(1, 0), sz);
	src[4] = px(p + ivec2(-1, 1), sz);
	src[3] = px(p + ivec2(0, 1), sz);
	src[2] = px(p + ivec2(1, 1), sz);
	src[15] = px(p + ivec2(-1, 2), sz);
	src[14] = px(p + ivec2(0, 2), sz);
	src[13] = px(p + ivec2(1, 2), sz);
	src[19] = px(p + ivec2(-2, -1), sz);
	src[18] = px(p + ivec2(-2, 0), sz);
	src[17] = px(p + ivec2(-2, 1), sz);
	src[9] = px(p + ivec2(2, -1), sz);
	src[10] = px(p + ivec2(2, 0), sz);
	src[11] = px(p + ivec2(2, 1), sz);

'''

TAIL = r'''
	// 收紧过渡带 (= 当初离线 6 倍流水线的 tighten): 软边收成约 1 像素宽的抗锯齿边
	float a = clamp((res.a - 0.3) / 0.4, 0.0, 1.0);
	ivec2 csz = textureSize(color6, 0);
	COLOR = vec4(texelFetch(color6, clamp(ivec2(floor(UV * vec2(csz))), ivec2(0), csz - 1), 0).rgb, a);
}
'''


def convert(src):
    body = src[src.index("float v[9];"):src.index("FragColor = vec4(res, 1.0);")]
    first = body.index("dist_01_04 = DistYCbCr(src[7], src[2]);")
    second = body.index("dist_01_04 = DistYCbCr(src[7], src[2]);", first + 1)
    body = body[:first] + body[second:]  # 原版把对角 1 的判定重复贴了一遍 (结果相同)
    body = re.sub(r"float v\[9\];\s*(v\[\d\] = reduce\(src\[\d\]\);\s*)+", "", body)
    body = re.sub(r"v\[\s*(\d+)\]\s*==\s*v\[\s*(\d+)\]", r"eq(src[\1], src[\2])", body)
    body = re.sub(r"v\[\s*(\d+)\]\s*!=\s*v\[\s*(\d+)\]", r"!eq(src[\1], src[\2])", body)
    body = re.sub(r"if \( (\(.*\)) == false\)\n", r"if (!\1)\n", body)
    old = "IsPixEqual(src[0], src[2]) == false) ) == false );"
    assert body.count(old) == 1
    body = body.replace(old, "!IsPixEqual(src[0], src[2])) ) );")
    old = "blendResult[2] >= BLEND_DOMINANT ||\n\t\t\t\t\t\t\t   (("
    assert body.count(old) == 1
    body = body.replace(old, "blendResult[2] >= BLEND_DOMINANT ||\n\t\t\t\t\t\t\t   !((")
    body = body.replace("IsBlendingNeeded(blendResult) == true", "IsBlendingNeeded(blendResult)")
    assert "false" not in body and "true" not in body
    assert "v[" not in body.replace("dst[", "").replace("src[", "")
    body = body.replace("vec3 dst[36];", "vec4 dst[36];").replace("vec3 blendPix", "vec4 blendPix").replace("vec3 res", "vec4 res")
    return HEAD + body.replace("\t\t", "\t").rstrip() + "\n" + TAIL


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = os.path.join(sys.argv[1], "edge-smoothing", "xbrz", "shaders", "6xbrz.slang")
    with open(path, encoding="utf-8") as f:
        out = convert(f.read())
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print("写出", os.path.normpath(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
