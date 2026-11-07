# API anahtarıyla okuma testi (yaklaşık 10 dakika, birkaç dolar)

Amaç: Uygulamanın AI okuyucusu çizimlerden doğru değerleri çıkarıyor mu, bunu ölçmek.
Kural motoru zaten test edildi. Eksik olan test okuma.

## 1. Hazırlık
1. Repoda `main` dalında ol (`git pull`).
2. Bu paketteki dosyaları repoya şöyle kopyala:
   - `tools/*.py` → `Since-AI/tools/`
   - `data/` klasörü → `Since-AI/data/` (synthetic, ground_truth, restricted)
3. Kurulum (bir kere yeterli):
   ```bash
   python -m venv .venv
   .venv/Scripts/pip install -r backend/requirements.txt reportlab
   ```
4. `.env.example` dosyasını `.env` olarak kopyala ve `ANTHROPIC_API_KEY=...` satırını doldur.
   `BUDGET_USD=4.00` kalsın. Harcama bu limitte durur.

## 2. Çalıştır
```bash
.venv/Scripts/python tools/eval_test_data.py
```
Okunan sonuçlar önbelleğe alınır, yani ikinci çalıştırma ücretsizdir.

## 3. Neye bakacaksın
Her dosya için `reader:` satırına bak:
- `found_correct`: doğru okunan değer sayısı
- `wrong_value`: yanlış okunan değer sayısı. **En kötüsü bu.**
- `missed`: kaçırılan değer sayısı
- `extra_facts`: fazladan okunan değer sayısı (Sikuliaq için 0 olmalı, çünkü çizimde kapı genişliği yazmıyor)

Beklenen değer sayıları:
- syn_01: 7
- syn_02: 10
- syn_03: 6
- Sikuliaq: 1 (boy). Kapı genişliği okunursa uydurmadır, mutlaka not et.

## 4. Bilinen sorun (şaşırma)
Sentetik çizimlerde kapılar okunsa bile pass/fail çıkmayacak. `check_door_clear_width` sadece 3D modelden gelen kapıları değerlendiriyor.
Okuma doğruluğunu `reading` sayıları gösterir, verdict sayıları değil.

## 5. Bana gönder
- `data/reports/eval.json` dosyası
- `data/reports/usage.json` dosyası (kaç dolar harcandığı)

Not: `data/restricted/` içindeki dosyaların lisansı belirsiz. Sadece ekip içinde kullan, GitHub'a koyma (zaten `.gitignore` içinde).
