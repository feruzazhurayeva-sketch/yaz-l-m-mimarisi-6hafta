# Architectural Overview - Increment 5: Error Handling, Validation & Dead-Letter Channel

> Önceki artırımlar (1–4: boru hattı iskeleti, tipli kayıt, filtreler, bildirimsel YAML + Stage Registry) korunmuştur; Artırım 5 hata yönetimini mimari bir konu olarak ekler. Artırım 4 diyagramı ve kavramları aşağıda "Increment 4" bölümünde durur.

## Increment 5 Architecture Diagram: Hat artık düz bir çizgi değil

```
  ANA BORU HATTI (main pipeline)
  ┌────────────┐   ┌─────────────┐   ┌──────────────┐   ┌─────────┐   ┌──────────┐   ┌──────────┐
  │FileLine    │──>│ ParserStage │──>│Validation    │──>│ Filter  │──>│ Project  │──>│ FileSink │  out/*.txt
  │Source      │   │ on_error:   │   │Stage         │   │         │   │          │   │ (ana     │
  │(satır)     │   │ DEAD_LETTER │   │on_error:     │   │         │   │          │   │  hedef)  │
  └─────┬──────┘   └──────┬──────┘   │ DEAD_LETTER  │   └─────────┘   └──────────┘   └──────────┘
        │                 │          └──────┬───────┘
        │ PipelineException               │ StageException + politika (motorun topolojik kararı)
        │ (okunamayan dosya,              │
        │  disk dolu, yapılandırma)       │
        v                                 v
  ╔═════════════╗       ┌─────────────────────────────────────────────────────────────┐
  ║ ÇALIŞTIRMAYI║       │ İKİNCİL, BAĞIMSIZ BORU HATTI (dead-letter pipeline)         │
  ║ DURDUR      ║       │                                                             │
  ║ (FAILED)    ║       │  FailedRecord(raw_input, stage_name, exception, timestamp)  │
  ╚═════════════╝       │        │                                                    │
                        │        v                                                    │
                        │  DeadLetterChannel ──> DeadLetterFileSink  out/dead-letter.jsonl
                        └─────────────────────────────────────────────────────────────┘

  Her iki hat da RunSummary'ye sayaç yazar:  giren = çıkan + elenen + skip + dead-letter
```

`FAIL_FAST` politikası ve `PipelineException`, hattı durduran üçüncü yoldur; `SKIP` kaydı yalnızca sayar; `DEAD_LETTER` kaydı tanılama bağlamıyla ikincil hatta yönlendirir; `RETRY(n)` aynı aşamada yeniden dener, hak bitince `retry_fallback` (varsayılan `DEAD_LETTER`) uygulanır.

---

## Declarative Architecture Diagram (Increment 4)
```
                          +-------------------------+
                          |   pipeline.yaml (DSL)   |
                          +-------------------------+
                                       |
                                       v
                             [ PipelineLoader ]  <--- (Fail Fast Validation)
                                       |
                     +-----------------+-----------------+
                     |                                   |
                     v                                   v
             [ StageRegistry ]                  [ PipelineBuilder ]
           (Dynamic Factory Map)                         |
                     |                                   v
                     +----------------------------> [ Pipeline Engine ]
                                                         |
                  +--------------------------------------+--------------------------------------+
                  |                                      |                                      |
                  v                                      v                                      v
         [ FileLineSource ]                     [ Processing Stages ]                     [ FileSink ]
```

---

## Architectural Concepts

### 1. Separation of Architectural Definition from Implementation
- İşlem hattının topolojisi ve veri akışı koddan soyutlanarak bildirimsel (declarative) YAML dosyalarına aktarılmıştır.
- **Kilometre Taşı Avantajı:** Yeni bir filtreleme veya analiz boru hattı kurmak için kod değişikliği veya yeniden derleme/dağıtım gerekmez; yalnızca yeni bir YAML yapılandırma dosyası tanımlanır.

### 2. Stage Registry Pattern (Veri Odaklı Eşleme)
- Kod içinde katı, sabit kodlanmış (`hardcoded`) `switch-case` veya zincirleme `if-else` blokları kullanılmamıştır.
- `StageRegistry` sınıfı, aşama adlarını karşılık gelen fabrika (factory) fonksiyonlarına bir sözlük eşlemi (`Map/Dictionary`) üzerinden bağlar.
- Yeni bir aşama eklendiğinde yalnızca `register_stage` metoduyla kayıt defterine tanımlanması yeterlidir (Açık/Kapalı Prensibi - OCP).

### 3. Fail Fast, Fail Loudly (Erken ve Gürültülü Başarısızlık)
- **Yapılandırma Zamanı (Config-Time) Hataları:** Dosya yolu eksikliği, bilinmeyen aşama adı, eksik parametre (`op`, `field` vb.) veya hatalı veri tipleri boru hattı inşa edilmeden önce `PipelineLoader` tarafından yakalanır ve net bir `ConfigurationError` fırlatılır. Tek bir satır log dahi işlenmeden süreç güvenle durdurulur.
- **Çalışma Zamanı (Runtime) Hataları:** Artırım 5 ile ikiye ayrılmıştır (aşağıdaki "Error Model" bölümü): tek kayıtlık sorunlar `StageException`, hattı sürdürülemez kılan sorunlar `PipelineException`.

---

## Configuration Schema (YAML Şeması)

```yaml
pipeline:
  name: <string>              # Boru hattı kimliği/açıklaması
  source:
    type: file                # Kaynak tipi: 'file'
    params:
      path: <string>          # Okunacak dosya yolu
  stages:
    - type: parse             # Ayrıştırıcı aşama
      params:
        format: clf           # Desteklenen format: 'clf'
    - type: filter            # Koşullu filtreleme
      params:
        field: <string>       # LogRecord alanı (status, path, bytes vb.)
        op: <string>          # Karşılaştırma operatörü: '>=', '<=', '==', '!=', 'startswith', 'contains'
        value: <any>          # Karşılaştırma değeri
    - type: project           # Veri minimizasyonu / projeksiyon
      params:
        fields: [<string>]    # Seçilecek alan listesi
  sink:
    type: file | console      # Hedef bileşen tipi
    params:
      path: <string>          # Çıktı dosya yolu ('file' seçildiyse zorunlu)
```


---

# Increment 5

## Error Model: `StageException` vs `PipelineException`

Fark **"hatanın kapsamı"** sorusuyla ayrılır: *sorun bir kayda mı ait, yoksa hattın kendisine mi?*

| | `StageException` | `PipelineException` |
|---|---|---|
| Anlamı | Bir aşamada **tek bir kayıt** işlenirken hata oluştu | **İşlem hattı devam edemez** |
| Kurtarılabilir mi? | **Evet** – hat sağlam, yalnızca o kayıt işlenemedi | **Hayır** – çalıştırma durur (`status = FAILED`) |
| Örnekler | kesik satır, UTF-8 olmayan bayt, negatif bayt, 1970/2099 tarihi, geçersiz IP, 100 KB'lık satır, boş satır, geçici I/O hatası | yapılandırma hatası (`ConfigurationError`, alt sınıf), kaynak dosyası bulunamıyor/okunamıyor, ana hedef dosyası açılamıyor/disk doluyor, dead-letter hedefine yazılamıyor |
| Kim karar verir? | Aşamanın **hata politikası** (`on_error`) | Hiçbir politika; **yutulamaz** |
| Sınıf ilişkisi | `Exception` | `Exception` (`StageException`'ın alt/üst sınıfı **değildir**) |
| Çıkış kodu (CLI) | 0 (diğer kayıtlar işlendi) | 1 (yapılandırma) / 2 (çalışma zamanı) |

Tasarım kuralları:
- Aşamalar yalnızca **ne olduğunu** bildirir (`raise StageException(...)`); kaydın **nereye gideceğine** aşama değil, motor (`Pipeline._dispatch`) ve yapılandırmadaki politika karar verir. Hata yönlendirmesi bu yüzden bir `try/catch` kararı değil **topolojik karardır**: aynı aşama, yapılandırmayı değiştirerek koda dokunmadan `SKIP`'ten `DEAD_LETTER`'a geçirilebilir.
- Hedef/kaynak (I/O) hataları (`OSError`) `PipelineException`'a çevrilir: dead-letter kanalı güvenilir değilse kayıtlar *sessizce* kaybolmasın diye hat durur.
- Aşamadaki beklenmeyen istisnalar (`ZeroDivisionError` gibi) kayıt düzeyinde `StageException`'a sarılır ve politikaya tabi olur; hata mesajında gerçek tür (`ZeroDivisionError: ...`) korunur.

## Error Policies (aşama başına, YAML'dan seçilir)

```yaml
stages:
  - type: parse
    on_error: DEAD_LETTER            # FAIL_FAST | SKIP | DEAD_LETTER | RETRY(n)
  - type: some_io_stage              # (6. hafta) ağ/disk aşamaları için
    on_error: RETRY(3)
    retry_delay_s: 0.5               # isteğe bağlı bekleme
    retry_fallback: DEAD_LETTER      # hak bitince; varsayılan DEAD_LETTER (FAIL_FAST/SKIP da olabilir)
```

| Politika | Davranış | Sayaç (RunSummary) |
|---|---|---|
| `FAIL_FAST` | `PipelineException` ile çalıştırmayı durdurur (varsayılan: sessizce atlamak yok) | `failed` |
| `SKIP` | Kaydı atar, **sayısını tutar** | `skipped` |
| `DEAD_LETTER` | `FailedRecord`'u ikincil kanala yönlendirir | `dead_lettered` |
| `RETRY(n)` | Aynı kaydı en fazla `n` kez yeniden dener; tükenirse `retry_fallback` | `retried` (+ fallback sayacı) |

- **Fail-fast yapılandırma:** `DEAD_LETTER` (veya fallback'i `DEAD_LETTER` olan `RETRY`) kullanan bir aşama varken `dead_letter:` hedefi tanımlı değilse `ConfigurationError` fırlatılır — tek satır okunmadan.
- `RETRY` uyarısı: yeniden deneme aşamanın `process` çağrısını baştan çalıştırır; aşama başarısız olmadan önce aşağı yönde kayıt yaymışsa (fan-out) yinelenme olabilir. Bu nedenle `RETRY` yalnızca kayıt başına tek çıktı üreten, idempotent I/O aşamaları için önerilir.

## Dead-Letter Channel

`FailedRecord(raw_input, stage_name, exception, timestamp)` taşıyan **ikinci ve bağımsız bir çıktı yoludur** (Python adlandırması: PDF'deki `rawInput/stageName` = `raw_input/stage_name`). Ek olarak `context` sözlüğü tanılama bilgisi taşır: `line_number`, `stage_index`, `attempts`, `policy`.

- `DeadLetterChannel`, ana hattın aşamalarını/hedefini **bilmez**; kendi `open/send/close` yaşam döngüsü ve sayacı vardır → ayrı bir boru hattı olarak diyagramda gösterilmiştir.
- Hedefi yapılandırmadan seçilir: `dead_letter: {type: dead_letter_file, params: {path: ..., max_raw_length: 500}}`. Çıktı JSON Lines'tır (bir satır = bir hata); ham girdi `max_raw_length`'te kesilir, tam uzunluk `raw_length` alanında kalır (100 KB'lık satır dosyayı şişirmez). UTF-8 olmayan baytlar `\udcXX` olarak yazılır, dosya geçerli UTF-8 kalır.

Örnek satır:
```json
{"timestamp": "2026-10-27T10:50:24+00:00", "stage": "validate", "exception_type": "StageException",
 "message": "Doğrulama başarısız: bytes=-1 alt sınırın (0) altında", "raw_length": 93, "raw_truncated": false,
 "raw": "10.0.0.5 - - [...] \"GET / HTTP/1.1\" 200 -1 ...", "line_number": 17, "stage_index": 1, "attempts": 1, "policy": "DEAD_LETTER"}
```

## ValidationStage (bildirimsel)

Kurallar YAML'dan gelir; kod değişmeden yeni doğrulama tanımlanır. Tüm ihlaller tek `StageException` mesajında toplanır, kaydın akıbetini aşamanın `on_error` politikası belirler.

```yaml
- type: validate
  on_error: DEAD_LETTER
  params:
    required_fields: [client_ip, method, path, status]     # zorunlu alanlar
    ranges: { status: {min: 100, max: 599}, bytes: {min: 0} }   # sayısal aralıklar
    timestamp: { min: "2000-01-01", max: now }              # zaman damgası tutarlılığı (now = şimdi + 1 gün tolerans)
    ip_format: true                                         # IPv4/IPv6 biçimi
    allowed_methods: [GET, POST]                            # isteğe bağlı
```
Hatalı kural (bilinmeyen anahtar, sayı olmayan sınır, geçersiz tarih...) `ConfigurationError` verir.

## RunSummary (8–9. haftalar için temel)

Her çalıştırmanın sonunda `Pipeline.run(print_summary=True)` (CLI her zaman) yazdırır: **gelen**, **çıkan**, **aşama başına** `giren / çıkan / elenen / skip / dead-letter / retry / failed`, **dead-letter toplamı**, **gerçek geçen süre** (`perf_counter`), `status` (COMPLETED/FAILED) ve durma nedeni.

Ölçüm için tasarım kararları:
- Sayaçlar yalnızca motor tarafından, **tek yerde** (`_dispatch`) güncellenir; aşamalar sayaç tutmaz (eski `ParserStage.error_count` kaldırıldı). Yeni aşama eklemek sayaç kodu gerektirmez.
- `RunSummary.to_dict()` JSON'a çevrilebilir (`--summary-json yol`), benchmark betikleri ve karşılaştırmalar için makine-okunur çıktıdır; `StageStats` aşama başına genişletilebilir (gecikme histogramı, bayt sayacı vb. alan eklemek yeterli).
- **Muhasebe değişmezi:** `giren = çıkan + Σ(elenen + skip + dead-letter + failed)`; `RunSummary.is_balanced` ile denetlenir ve özette "DENGELİ ✓" olarak basılır (kayıt başına en fazla bir çıktı veren aşamalar için geçerlidir; fan-out aşaması eklenirse tanım genişletilmelidir). Hata/duraklama durumunda da özet üretilir.
- Süre, çalıştırmanın tamamını (aç/işle/kapat) kapsar. Aşama başına süre bilinçli olarak yoktur: push modelinde bir aşamanın süresi alt aşamaları da içerir; 8. haftada ayrıştırılmış ölçüm eklenecektir.

## Kaos Testi: bozuk dosyadaki her hata türü → onu ele alan politika

`data/access-dirty.log` (`python tools/make_dirty_log.py` ile belirli/tekrarlanabilir üretilir): 63 satır = 40 geçerli + 23 bozuk. Çalıştırma: `python src/main.py -c configs/dirty-report.yaml`. Boş dosya için `data/empty.log` (0 bayt).

| # | Hata türü (dosyada kaç satır) | Hatayı yakalayan aşama | Fırlatılan | Uygulanan politika | Sonuç / hedef |
|---|---|---|---|---|---|
| 1 | Kesilmiş satır (5) | `parse` | `StageException` ("CLF desenine uymuyor") | `DEAD_LETTER` | `dead-letter.jsonl` |
| 2 | UTF-8 olmayan bayt (3) | `parse` | `StageException` ("geçerli UTF-8 değil") | `DEAD_LETTER` | `dead-letter.jsonl` |
| 3 | Boş / yalnızca boşluk satırı (2) | `parse` | `StageException` ("Boş satır") | `DEAD_LETTER` | `dead-letter.jsonl` |
| 4 | 100 KB'lık tek satır (1) | `parse` (`max_line_length: 8192`) | `StageException` ("çok uzun") | `DEAD_LETTER` | `dead-letter.jsonl` (ham girdi 200 karaktere kesilir, tam uzunluk kayıtlı) |
| 5 | Negatif bayt sayısı (3) | `validate` (`ranges.bytes.min: 0`) | `StageException` | `DEAD_LETTER` | `dead-letter.jsonl` |
| 6 | 1970 zaman damgası (2) | `validate` (`timestamp.min`) | `StageException` | `DEAD_LETTER` | `dead-letter.jsonl` |
| 7 | 2099 zaman damgası (2) | `validate` (`timestamp.max: now`) | `StageException` | `DEAD_LETTER` | `dead-letter.jsonl` |
| 8 | Geçersiz IP (3) | `validate` (`ip_format`) | `StageException` | `DEAD_LETTER` | `dead-letter.jsonl` |
| 9 | Geçersiz durum kodu (2) | `validate` (`ranges.status`) | `StageException` | `DEAD_LETTER` | `dead-letter.jsonl` |
| 10 | Boş dosya (`empty.log`) | — | hata yok | — | 0 giren / 0 çıkan, `COMPLETED` |
| 11 | Dosya yok/okunamıyor (kaos dışı) | `FileLineSource` | `PipelineException` | politika uygulanmaz | çalıştırma `FAILED`, çıkış kodu 2 |

Beklenen özet: **63 gelen = 40 çıkan + 23 dead-letter** (`parse` 11 + `validate` 12), "DENGELİ ✓". Aynı dosya `parse` için `SKIP`'e çevrilirse 11 kayıt yalnızca sayılır (`skipped`), `FAIL_FAST`'e çevrilirse ilk bozuk satırda çalıştırma durur — üçü de `tests/test_chaos.py` ve `tests/test_policies.py` içinde sınanır.

Not (tasarım): UTF-8 olmayan baytlar kaynakta `errors="surrogateescape"` ile okunur; böylece dosyanın geri kalanı okunabilir kalır ve bozuk satır, ham baytlarını koruyarak ayrıştırıcıda kurtarılabilir bir `StageException`'a dönüşür (kaynak çökmez).
