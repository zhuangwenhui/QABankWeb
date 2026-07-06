"""图片验证码:自包含、离线可用,基于 Pillow 服务端栅格化生成。

设计要点:
- 字符集剔除易混淆字符(0/O/1/I/l/2/Z 等);默认 4 位、大小写不敏感。
- 答案不以明文进入会话:Flask 默认会话是"签名但可读"的客户端 Cookie,
  若把明文验证码写进会话,机器人读自己的 Cookie 即可得到答案。
  因此只存 HMAC-SHA256(SECRET_KEY, 答案) 摘要,校验时重算摘要做常量时间比较,
  机器人拿到 Cookie 里的摘要也无法反推 4 位答案(缺少服务端 SECRET_KEY)。
- 一次性使用(校验即从会话弹出)+ 有效期,抵御重放。
"""
import hashlib
import hmac
import io
import os
import random
import time

from flask import current_app, session
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CHARS = 'ABCDEFGHJKLMNPQRSTUVWXY3456789'  # 去掉易混淆的 0 1 2 I O Z
LENGTH = 4
WIDTH, HEIGHT = 160, 50
TTL_SECONDS = 300              # 验证码有效期
SESSION_KEY = '_captcha'

_FONT_CANDIDATES = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
]


def _load_font(size):
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _rand_color(lo=0, hi=255):
    return (random.randint(lo, hi), random.randint(lo, hi), random.randint(lo, hi))


def _digest(answer):
    """HMAC(SECRET_KEY, 归一化答案)。归一化:去空白 + 转大写。"""
    key = current_app.secret_key
    if isinstance(key, str):
        key = key.encode('utf-8')
    norm = (answer or '').strip().upper().encode('utf-8')
    return hmac.new(key, norm, hashlib.sha256).hexdigest()


def _render(text):
    """把验证码文本渲染成带干扰的 PNG 字节。"""
    bg = _rand_color(210, 255)
    img = Image.new('RGB', (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img)

    # 背景噪点
    for _ in range(int(WIDTH * HEIGHT * 0.06)):
        draw.point((random.randint(0, WIDTH), random.randint(0, HEIGHT)), fill=_rand_color(120, 220))
    # 干扰线
    for _ in range(5):
        draw.line(
            [(random.randint(0, WIDTH), random.randint(0, HEIGHT)),
             (random.randint(0, WIDTH), random.randint(0, HEIGHT))],
            fill=_rand_color(100, 200), width=1)

    # 逐字符:各自旋转后贴回,位置抖动,深色随机
    font = _load_font(32)
    margin = 12
    step = (WIDTH - 2 * margin) // LENGTH
    x = margin
    for ch in text:
        layer = Image.new('RGBA', (step + 6, HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((3, 4), ch, font=font, fill=_rand_color(0, 110))
        layer = layer.rotate(random.uniform(-25, 25), expand=1, resample=Image.BICUBIC)
        img.paste(layer, (x, random.randint(0, 8)), layer)
        x += step

    img = img.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def issue():
    """生成一枚验证码:摘要写入会话,返回 PNG 字节供响应输出。"""
    text = ''.join(random.choice(CHARS) for _ in range(LENGTH))
    session[SESSION_KEY] = {'d': _digest(text), 'exp': time.time() + TTL_SECONDS}
    return _render(text)


def verify(submitted):
    """校验用户输入;一次性(无论成败都清除会话中的验证码)。"""
    data = session.pop(SESSION_KEY, None)
    if not data or not submitted:
        return False
    if time.time() > data.get('exp', 0):
        return False
    return hmac.compare_digest(data.get('d', ''), _digest(submitted))
