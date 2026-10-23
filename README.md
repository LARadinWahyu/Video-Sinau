# Video Promo SINAU — Pembelajaran Braille

Proyek ini menghasilkan video promosi tanpa narasi dengan fokus pada dua fitur utama: **scan/penerjemahan Braille** dan **pembelajaran Braille bertahap**.

## Output

- `sinau-braille-promo.mp4` — video final 1920×1080 (16:9), 45 detik, H.264 + AAC
- `poster.png` — key visual 1920×1080
- `storyboard.png` — enam frame utama beserta timestamp
- `music-original.wav` — musik instrumental yang dibuat secara programatis untuk video ini
- `generate_video.py` — generator seluruh visual dan audio

## Arah visual

Visual mengikuti referensi gambar yang diberikan: antarmuka kartu yang bersih, sudut membulat, navigasi merah aktif, ruang putih yang lapang, serta kombinasi warna utama:

- Merah: `#990000`
- Biru tua: `#123B63`
- Putih: `#FFFFFF`
- Warna pendukung: abu-abu muda, merah pucat, biru pucat, dan aksen emas

## Storyboard (45 detik)

| Waktu | Adegan | Pesan utama |
|---|---|---|
| 00:00–00:05.5 | Pembuka | “Sentuh titiknya. Temukan maknanya.” |
| 00:05.5–00:10 | Nilai produk | Belajar dan menerjemahkan Braille dalam satu aplikasi |
| 00:10–00:22 | Fitur Scan | Arahkan kamera, pindai pola titik, baca hasil terjemahan |
| 00:22–00:34 | Fitur Belajar | Materi bertahap, latihan interaktif, pantau progres |
| 00:34–00:40 | Dampak | Menjembatani karya Braille dengan lebih banyak pembaca |
| 00:40–00:45 | Penutup | “Belajar. Pindai. Pahami.” |

## Render ulang

Dari folder proyek:

```bash
../.venv/bin/python generate_video.py
```

Generator tidak mengunduh gambar, musik, atau aset pihak ketiga. Seluruh bentuk UI, pola Braille, transisi, dan musik dibuat secara programatis. Font yang digunakan adalah Noto Sans yang tersedia di sistem.
