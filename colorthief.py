import struct, zlib, random, math

def _decode_png(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    chunks = {}
    i = 8
    while i < len(data):
        length = struct.unpack('>I', data[i:i+4])[0]
        ctype  = data[i+4:i+8]
        cdata  = data[i+8:i+8+length]
        chunks.setdefault(ctype, []).append(cdata)
        i += 12 + length
    ihdr             = chunks[b'IHDR'][0]
    w, h, bd, ct     = struct.unpack('>IIBB', ihdr[:10])
    raw  = zlib.decompress(b''.join(chunks[b'IDAT']))
    bpp  = 3 if ct in (2, 3) else 4
    pixels = []
    stride = w * bpp + 1
    for row in range(h):
        base = row * stride + 1
        for col in range(w):
            o = base + col * bpp
            pixels.append((raw[o], raw[o+1], raw[o+2]))
    return pixels

def _decode_jpeg(data):
    pixels = []
    i = 0
    width = height = 0
    while i < len(data) - 1:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i+1]
        if marker in (0xC0, 0xC2):
            height = struct.unpack('>H', data[i+5:i+7])[0]
            width  = struct.unpack('>H', data[i+7:i+9])[0]
            break
        length = struct.unpack('>H', data[i+2:i+4])[0] if i+4 <= len(data) else 2
        i += 2 + length
    return None, width, height

def _pixels_from_bytes(data):
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return _decode_png(data)
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data)).convert('RGB')
        img.thumbnail((100, 100))
        return list(img.getdata())
    except ImportError:
        pass
    return []

def _dist(a, b):
    return sum((x-y)**2 for x, y in zip(a, b))

def _saturation(c):
    mx = max(c) / 255
    mn = min(c) / 255
    return (mx - mn) / (mx + 1e-9)

def _kmeans(pixels, k, iters=15):
    if len(pixels) < k:
        return pixels
    centers = random.sample(pixels, k)
    for _ in range(iters):
        buckets = [[] for _ in range(k)]
        for p in pixels:
            best = min(range(k), key=lambda j: _dist(p, centers[j]))
            buckets[best].append(p)
        for j in range(k):
            if buckets[j]:
                n = len(buckets[j])
                centers[j] = tuple(sum(p[c] for p in buckets[j])//n for c in range(3))
    return sorted(centers, key=_saturation, reverse=True)

def get_palette(data, color_count=6):
    pixels = _pixels_from_bytes(data)
    if not pixels:
        return [(128, 128, 128)] * color_count
    step = max(1, len(pixels) // 2000)
    sampled = pixels[::step]
    return _kmeans(sampled, color_count)
