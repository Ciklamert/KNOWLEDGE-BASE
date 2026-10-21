# 2 — Sistem nasıl çalışır (genel mimari)

## 2.1 Tek süreç, tek port
`brain serve` tek bir Python süreci başlatır (FastAPI). Aynı port (varsayılan 8765) üzerinden:
- **web arayüzü** (`/`): insanlar için;
- **REST API** (`/api/...`): betikler ve ajanlar için;
- **MCP** (`/mcp`): yapay zekâ ajanlarının araçları için;
- **webhook'lar** (`/webhooks/...`): GitLab ve TFS bildirimleri için.

Ayrı bir veritabanı sunucusu, kuyruk sunucusu veya ön yüz derlemesi yoktur. Bütün durum `data/` klasöründeki
dosyalardadır.

## 2.2 Parçalar

| Parça | Dosya | Görevi (basitçe) |
|---|---|---|
| Ayarlar | `brain/settings.py` | Bütün ayarların tek şeması; `.env` dosyasını okur/yazar; arayüzdeki Settings sayfası buradan üretilir |
| Arka plan işleri | `brain/jobs.py` | Uzun işler (indeksleme, yükleme, ajanlar) ilerleme yüzdesi ve hatasıyla arka planda çalışır |
| Kurumsal API istemcisi | `brain/llm.py` | Kurumsal API ile konuşan **tek** kod: sohbet, embedding, model listesi |
| Vektör önbelleği | `brain/vcache.py` | Her embedding'i model + metin başına bir kez saklar; aynı metin ikinci kez API'ye gitmez |
| Kod grafiği motoru | `brain/providers/codebase_memory.py` | Hazır `codebase-memory-mcp` programını yönetir (yerel, CPU, internet yok) |
| Çok dilli kod vektörleri | `brain/codevec.py` | Kod sembollerini kurumsal embedding modeliyle vektöre çevirir; Türkçe soru İngilizce kodu bulur |
| Doküman motoru | `brain/providers/docgraph.py` | Dokümanların pasajları, anahtar kelime indeksi, vektörleri, kavramları, kuralları |
| Doküman dönüştürücü | `brain/providers/convert.py` | Her formatı Markdown'a ve resimlere çevirir |
| Doküman grameri | `brain/providers/docgrammar.py` | Resmî dokümanlarda bölüm/madde/fıkra ağacı, atıflar, tanımlar, yükümlülükler |
| OCR | `brain/ocr.py` | Görsel model yoksa veya yavaşsa resimdeki yazıyı yerelde okur (isteğe bağlı) |
| Arama | `brain/search.py` | Kod, kod vektörleri ve dokümanları birlikte arar, birleştirir, sıralar |
| Ajanlar | `brain/agents.py` | Sor, prompt iyileştir, proje rehberi; araç kullanan model döngüsü |
| Gereksinim yazıcı | `brain/srs.py` | Kurumun kendi formatında yazılım gereksinimleri yazar |
| Repolar | `brain/repos.py` | Klonlama, güncelleme, setler, dal katmanları, ana dallar |
| Dal kayması | `brain/drift.py` | Geliştiricinin dalı ana dalın gerisinde mi, çakışma riski var mı |
| Karar hafızası | `brain/memory.py` | Kararlar, kurallar, tuzaklar ve konvansiyonlar |
| Webhook'lar | `brain/webhooks.py` | GitLab/TFS bildirimlerini doğrular ve işler |
| MCP | `brain/mcp.py` | Ajan araçları (18 araç) |
| Arayüz | `brain/ui/` | Derleme gerektirmeyen tek sayfa (düz JavaScript) |

## 2.3 Başlangıçta ne olur?
1. Her reponun webhook gizli anahtarı yoksa üretilir.
2. Üç başlangıç işi paralel başlar: **kod grafiği motoru**, **doküman motoru** (eksik vektörleri ve resim
   açıklamalarını tamamlar) ve **kurumsal API kontrolü** (bir küçük sohbet ve bir embedding çağrısı).
3. Hazır olunca `READY` yazılır. Ardından `BRAIN_SYNC_ON_START` açıksa tüm repolar güncellenir.
4. Sürekli çalışan iki döngü başlar: her dakika "24 saattir güncellenmemiş repo var mı" kontrolü (bunun içinde
   süresi dolan dal katmanlarının silinmesi ve günlük önbellek temizliği de vardır) ve yerel çalışma kopyalarının
   izlenmesi. Doküman motoru da her 10 dakikada bir eksik işleri tamamlar.

## 2.4 Bir repo güncellemesi nasıl akar?
Webhook, git hook, düğme, CLI, MCP `sync_repo`, başlangıç veya zamanlayıcı → `repos.request_sync`:
1. Çalışma kopyası ana dala getirilir (sunucu klonu: `fetch` + `reset --hard`; yerel kopya: temiz ve ana daldaysa
   `pull --ff-only`).
2. Kod motoru yalnızca değişen dosyaları yeniden işler.
3. Değişen sembollerin kod vektörleri güncellenir (önceden görülen metinler önbellekten gelir).
4. İndekslenen commit `data/state.json` dosyasına yazılır.
5. Sunucuda artık olmayan dalların katmanları silinir (`git ls-remote --heads`).
6. Diğer ana dalların (`develop` vb.) başı ilerlemişse onlar da yeniden indekslenir.

Güncelleme sürerken aynı repo için yeni bir istek gelirse kaybolmaz: güncelleme bitince bir kez daha çalışır.

## 2.5 Bir doküman yüklemesi nasıl akar?
1. Orijinal dosya `data/originals/` içine saklanır.
2. Dosya Markdown'a ve resimlerine çevrilir (`data/converted/<dosya>.md`).
3. Başlıklar ve sayfalar boyunca **pasajlara** bölünür (metin, tablo, resim).
4. Anahtar kelime indeksi, kavramlar, kurallar, madde ağacı ve dokümanlar arası bağlar çıkarılır. **Doküman bu
   noktada hiçbir model çağrısı olmadan aranabilir.**
5. Arka planda: pasaj vektörleri (toplu embedding), sonra resimler (önbellek, görsel model veya OCR).

Ayrıntı: [04](04-DOKUMAN-MOTORU.md).

## 2.6 Canlı arayüz
Her görünür değişiklik (iş adımı, doküman, repo, ayar, webhook) tek bir sayacı artırır. Tarayıcı `/api/events`
üzerinden bunu dinler ve açık sayfayı kendiliğinden yeniler; sayfayı yeniden yüklemeye gerek yoktur.

## 2.7 Depolama (`data/` klasörü)

| Yol | İçerik | Silinebilir mi? |
|---|---|---|
| `cbm/<proje>.db` | Kod grafiği ve yerel kod vektörleri (repo veya dal katmanı başına) | Evet: sonraki güncellemede yeniden oluşur |
| `codevec/<proje>.npz` | Çok dilli kod vektörleri | Evet: yeniden oluşur (önbellek sayesinde API maliyeti düşük) |
| `vectors.db` | Embedding önbelleği (model + metin → vektör) | Evet: sonraki embedding'ler yeniden API'ye gider |
| `repos/<ad>/` | Sunucunun yönettiği klonlar | Evet: yeniden klonlanır |
| `worktrees/<repo>--<dal>/` | Dal katmanlarının çalışma kopyaları | Önce arayüzden katmanı kaldırın |
| `docs/docs.db` | Doküman motoru (pasajlar, indeks, vektörler, kavramlar, resim açıklama önbelleği) | `originals/` duruyorsa evet: **Re-index all** yeniden kurar |
| `docs/assets/` | Dokümanların resimleri | `docs.db` ile birlikte |
| `originals/` | Yüklenen dosyaların aslı | **Saklayın**: yeniden indekslemenin kaynağı |
| `converted/` | Dönüştürülmüş Markdown | Evet |
| `memory/` | Karar hafızası | **Saklayın**: yalnızca yedekte vardır |
| `srs/` | Gereksinim formatları ve yazılmış şartnameler | Saklayın |
| `state.json` | Repo başına indekslenen commit, dal katmanları | Evet |
| `logs/` | Sunucu ve kod motoru günlükleri | Evet |

Yedek = `data/`, `.env` ve `repos.json` kopyası.

## 2.8 Tasarım ilkeleri
1. **Metin analizi yetiyorsa model çağrılmaz.** İndeksleme ayrıştırıcılar, anahtar kelime indeksleri ve graf
   istatistikleriyle yapılır; model soru anında ve resimler için kullanılır.
2. **Her şeyden bir tane.** Tek süreç, tek port, tek ayar şeması, tek yapılandırma dosyası, tek iş mekanizması,
   her işlevin kullandığı tek arama.
3. **Yavaşla ama durma.** Her model adımının bir yedeği vardır (resimler için OCR, arama için anahtar kelime);
   başarısız bir adım sonra tamamlanır.
4. **Asla iki kez ödeme.** Bir embedding veya resim açıklaması, metin veya resim başına bir kez hesaplanır.
5. **Değiştirilebilir motorlar.** Motora özgü kod yalnızca `brain/providers/` içindedir.
6. **Yalnızca yerel durum.** SQLite ve düz dosyalar; yedek bir klasör kopyasıdır.
7. **Önce kanıt.** Her cevap, prompt ve şartname, yanında gösterilen arama sonuçlarından üretilir.
