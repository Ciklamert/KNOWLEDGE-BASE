# 7 — Ayarlar, işletim, güvenlik ve testler

## 7.1 Ayarlar nasıl çalışır?
- Bütün ayarlar tek bir şemada tanımlıdır (`brain/settings.py`). `.env.example` ve
  [03-CONFIGURATION.md](../03-CONFIGURATION.md) bu şemadan otomatik üretilir; yani belge ile kod hep aynıdır.
- Değerler `.env` dosyasında durur. Arayüzdeki **Settings** sayfası (git sunucuları ve webhook ayarları için
  **Repositories** sayfası) aynı dosyayı düzenler ve değeri doğrular.
- Çoğu ayar **anında** geçerli olur. Bazıları bir motorun veya sunucunun yeniden başlatılmasını gerektirir; arayüz
  bunu söyler.
- Ortam değişkenleri de çalışır; `.env` dosyası önceliklidir.

Önemli gruplar:

| Grup | Örnek ayarlar |
|---|---|
| Server | `BRAIN_HOST`, `BRAIN_PORT`, `BRAIN_UI_PASSWORD`, `BRAIN_API_TOKEN`, `BRAIN_TLS_CERT`, `BRAIN_DATA_DIR` |
| Corporate API | `BRAIN_LLM_BASE_URL`, `BRAIN_LLM_MODEL`, `BRAIN_EMBEDDING_MODEL`, `BRAIN_VLM_MODEL`, `BRAIN_VLM_TIMEOUT`, `BRAIN_VLM_MAX_PER_HOUR`, `BRAIN_EMBED_BATCH`, `BRAIN_VECTOR_CACHE`, `BRAIN_VECTOR_CACHE_DAYS` |
| Relevance / Search | `BRAIN_RERANK`, `BRAIN_DOC_BRIDGE`, `BRAIN_GRAPH_EXPAND`, `BRAIN_QUERY_EXPANSION`, `BRAIN_EMBED_BUDGET`, `BRAIN_SEARCH_DETAIL` |
| Ajanlar | `BRAIN_ASK_*`, `BRAIN_ENHANCE_*`, `BRAIN_GUIDE_*`, `BRAIN_SRS_*`, `BRAIN_AGENT_TOOL_CALLING` |
| Code graph | `CBM_INDEX_MODE`, `BRAIN_CODE_VECTORS`, `BRAIN_CODE_VECTORS_MAX` |
| Updates & webhooks | `BRAIN_DEFAULT_BRANCH`, `BRAIN_OTHER_MAIN_BRANCHES`, `BRAIN_BRANCH_TTL_DAYS`, `BRAIN_BRANCH_UPDATE_ON_PUSH`, `BRAIN_SYNC_INTERVAL_MINUTES`, `BRAIN_WEBHOOK_EVENTS` |
| Document graph | `BRAIN_DOC_CHUNK_CHARS`, `BRAIN_CONCEPT_SIM`, `BRAIN_PICTURE_MIN_PX`, `BRAIN_OCR`, `BRAIN_OCR_MIN_SCORE` |

## 7.2 Yavaş bir kurumsal API için önerilen değerler
Sistem zaten şu dört kurala göre tasarlanmıştır: kullanıcı API'yi beklemez, aynı iş iki kez ödenmez, yük
sınırlanır, API yokken de yerel bir taban çalışır. Geriye yalnızca ayar kalır:

| Ayar | Değer | Neden |
|---|---|---|
| `BRAIN_EMBED_BATCH` | 32 | Küçük istekler ağ geçidi zaman aşımından önce biter |
| `BRAIN_EMBED_PARALLEL` | 2 | Paylaşılan ağ geçidini boğmaz |
| `BRAIN_EMBED_BUDGET` | 2 | Arama, embedding gecikirse anahtar kelimelerle cevaplar |
| `BRAIN_LLM_TIMEOUT` | 300 | Uzun ajan ve gereksinim çağrıları kesilmez |
| `BRAIN_VLM_TIMEOUT` | 60 | Yavaş bir resmi OCR devralır, kuyruk tıkanmaz |
| `BRAIN_VLM_MAX_PER_HOUR` | 30 | Ağ geçidinde insanlara kapasite bırakır |
| `BRAIN_QUERY_EXPANSION` | false | Sor/iyileştir başına bir sohbet çağrısı tasarruf |
| `BRAIN_AGENT_TOOL_CALLING` | off | Birkaç araç turu yerine tek kanıtlı çağrı: yavaş sohbet modelinde en büyük kazanç |

Eklemeyin: yerel LLM veya embedding modeli, kuyruk sunucusu, her sonucu API ile yeniden sıralama. Az kazanç için
çok hareketli parça getirirler.

## 7.3 İzleme
- `GET /healthz` (kimlik istemez): ayakta mı. `GET /api/status`: hazır mı, motorlar, API kontrolü, işler.
- Arayüz: **Overview** (motorlar, API, ajanlar, işler) ve **Logs**.
- Günlükler: `data/logs/server.log`, `data/logs/codebase-memory.log`.

## 7.4 Model değiştirmek

| Değişiklik | Etkisi |
|---|---|
| Sohbet modelleri | Anında, sonraki istek için; arayüzdeki açılır listeler istek başına model seçer |
| `BRAIN_VLM_MODEL` | Anında: açıklanmamış ve OCR ile okunmuş resimler 10 dakika içinde açıklanır |
| `BRAIN_EMBEDDING_MODEL` / `BRAIN_EMBEDDING_DIM` | Doküman motoru yeniden başlar ve her şeyi yeniden embed eder; kod vektörleri sonraki güncellemede yenilenir. Önbellek modele göre ayrıldığı için eski modele geri dönmek bedavadır |

## 7.5 Güvenlik
- Sunucu, ağ adresinde parolasız dinlemeyi reddeder.
- Çerezler HMAC ile imzalıdır; durum değiştiren arayüz istekleri ayrıca bir CSRF başlığı ister.
- Webhook anahtarları sabit zamanlı karşılaştırılır; git tokenları hata mesajlarında maskelenir.
- Veri sunucudan yalnızca kurumsal API'ye çıkar: embedding için doküman pasajları ve kod metinleri, görsel model
  için resimler, ajanlar için arama sonuçları. OCR kuruluysa resimleri sunucuda okur.
- İsteğe bağlı HTTPS (`BRAIN_TLS_CERT`, `BRAIN_TLS_KEY`) veya ters proxy.
- Ayrıntı: [12-SECURITY.md](../12-SECURITY.md).

## 7.6 Yedekleme, geri yükleme, yükseltme
- **Yedek:** sunucuyu durdurup `data/`, `.env` ve `repos.json` kopyalanır. Kod grafikleri git'ten, doküman grafiği
  `data/originals/` klasöründen yeniden kurulabilir; karar hafızası (`data/memory/`) yalnızca yedekte vardır.
- **Yükseltme:** yedek al → program dosyalarını değiştir (`.env`, `repos.json`, `data/`, `.venv/` kalsın) → kurulumu
  yeniden çalıştır → başlat.

## 7.7 Sorun giderme

| Belirti | Çözüm |
|---|---|
| Giriş "yanlış parola" diyor | `BRAIN_UI_USER`, `BRAIN_UI_PASSWORD` büyük/küçük harf duyarlı; 5 hatadan sonra 60 sn bekleyin |
| Vektörler pasaj sayısının altında kalıyor | Embedding uç noktası hata vermiş ("vectors postponed"); API düzelince 10 dakika içinde tamamlanır; anahtar kelime araması bu arada çalışır |
| Resimler açıklanmıyor | `BRAIN_VLM_MODEL` boş/yanlış veya saatlik bütçe dolmuş; OCR kuruluysa bu arada yazıları okur (`brain doctor`) |
| Görsel ağ geçidi yavaş | `BRAIN_VLM_TIMEOUT` veya `BRAIN_VLM_MAX_PER_HOUR` değerini düşürün |
| Silinen dalın katmanı duruyor | Webhook'ta tüm dallar için push olayları açık olmalı; yoksa sonraki repo güncellemesi siler ya da ✕ |
| Repo güncellemesi başarısız | Sunucu adresi, token, proxy, TLS (`BRAIN_GIT_CA_BUNDLE`), yerel yol |
| Kod motoru çalışmıyor | Antivirüs yanlış alarmı: `bin\windows\codebase-memory-mcp.exe` dosyasını SHA-256 ile izinli listeye ekleyin |
| Sor/iyileştir "tool calling not supported" | Otomatik yedek mod yeterli veya `BRAIN_AGENT_TOOL_CALLING=off` |
| Meslektaşlar arayüzü açamıyor | Güvenlik duvarında `BRAIN_PORT`; `BRAIN_HOST=0.0.0.0` |

Ayrıntı: [13-OPERATIONS.md](../13-OPERATIONS.md).

## 7.8 Testler
- **Statik testler** (sunucu gerekmez): `.venv\Scripts\python tests\test_static.py`. Python sürümü, modüller,
  ayar belgelerinin güncelliği, her route ve MCP aracının belgelenmiş olması, prompt analizi, repolar, webhook'lar,
  dal katmanlarının silinmesi/uzlaştırılması/süre dolumu, birden fazla ana dal, vektör önbelleği, resimler ve OCR,
  doküman dönüştürme ve anlama, karar hafızası, paketler ve belgelerdeki her bağlantı kontrol edilir.
- **Uçtan uca test:** sahte bir kurumsal API (`tests/mock_openai.py`) ve gerçek motorlarla `tests/smoke_test.py`:
  kimlik doğrulama, doküman yükleme ve arama, sor, iyileştir, MCP, webhook'lar, dal kayması, dal katmanları,
  yerel pull, ayarlar.
- **Doküman motoru değerlendirmesi:** `python tests/eval/run_eval.py` (12 dokümanlık Türkçe/İngilizce derlem, 36
  soru); `--with-api` ile gerçek embedding modelinizle ölçer.

Ayrıntı: [15-TESTING.md](../15-TESTING.md).
