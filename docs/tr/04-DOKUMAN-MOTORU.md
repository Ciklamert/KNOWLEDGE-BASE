# 4 — Doküman motoru

Doküman motoru AI-BRAIN'in içinde yerleşiktir (`brain/providers/docgraph.py`). Tek bir SQLite dosyası
(`data/docs/docs.db`) ve resim klasörü kullanır. En önemli özelliği: **her pasaj için model çağrısı yapmaz**. Bu
yüzden yavaş bir kurumsal API'de bile doküman yüklendiği anda aranabilir.

## 4.1 Her şey önce Markdown olur
Yüklenen her dosya içeriğine bakılarak tanınır ve Markdown'a çevrilir (MarkItDown fikri):
- **PDF:** okuma sırası, yazı boyutundan başlıklar, çizgili tablolar, resimler; taranmış veya çizim içeren sayfalar
  bütün olarak resme çevrilir; sayfa üst/alt bilgileri atılır;
- **Word, PowerPoint, Excel:** başlıklar, tablolar, grafik verileri, konuşmacı notları;
- HTML, CSV, JSON, XML, RSS, Jupyter defterleri, EPUB, ekli e-postalar, zip arşivleri, resimler (EXIF bilgisiyle),
  kaynak kod ve düz metin.

Dönüştürülmüş metin arayüzde *Markdown* düğmesiyle görülebilir.

## 4.2 Pasajlar
Markdown başlıklar ve sayfalar boyunca **pasajlara** bölünür:
- metin pasajları (paragraflar bütün kalır, en fazla `BRAIN_DOC_CHUNK_CHARS` = 1500 karakter);
- tablo pasajları (40 satırlık parçalar, başlık satırı tekrarlanır);
- resim pasajları (alt metin ve başlık; açıklama sonra eklenir).

Her pasaj doküman adı, bölüm yolu (`Sözleşme › 4 Ödemeler › 4.2 İadeler`) ve sayfa numarasıyla saklanır.

## 4.3 Model çağırmadan çıkarılanlar
- **Anahtar kelime indeksi** (SQLite FTS5, BM25): Türkçe harfler birleştirilir (ı = i, aksanlar kaldırılır) ve
  kelimeler köklerine indirgenir (Türkçe ek atma, İngilizce için Snowball). "onaylar", "onayı", "onaylanması" aynı
  köke düşer.
- **Kavramlar:** büyük harfli çok kelimeli adlar, kısaltmalar (KDV), kod tanımlayıcıları (`chargeCustomer`),
  tırnak içindeki terimler, dokümanda tekrar eden ikili ifadeler.
- **Tanımlar:** "Terim: tanım" satırları ve iki sütunlu sözlük tabloları.
- **İş kuralları:** zorunluluk (-malıdır, must, shall), yasak, tavsiye ve sınırlar ("5.000 TL üzeri", "en geç 3 iş
  günü") ile sayılar içeren tablo satırları.
- **Dokümanlar arası bağlar:** bir dokümanın diğerinin adını anması.
- **Doküman kartı:** anahtar cümleler, tarihler, sürüm, yürürlük tarihi, doküman numarası; aynı dokümanın eski
  sürümü işaretlenir ve aramada yenisinin altına düşer.

## 4.4 Doküman grameri (resmî ve teknik dokümanlar)
Kod nasıl ayrıştırılıyorsa resmî dokümanlar da öyle ayrıştırılır (`docgrammar.py`):
- **Birim ağacı:** bölüm, madde, fıkra, bent, alt bent; "Section 1.01", "ARTICLE 2", "4.3", "A. Amaç", gereksinim
  numaraları (REQ-004), geçici maddeler.
- **Atıflar:** "2 nci maddenin (2) numaralı fıkrası", "birinci fıkranın (a) bendi", "Section 3.1(a)", kanunlar
  (6698 sayılı ...), standartlar (ISO/IEC 27001). Atıflar hedef birime bağlanır.
- **İfadeler:** kim, ne yapmalı, hangi koşulda, hangi istisnayla (RFC 2119, Türkçe özne/yüklem, edilgen yapılar,
  kullanıcı hikâyeleri, Given/When/Then).

MCP ve REST `doc` aracı bunları sunar: `outline` (içindekiler), `unit` ("Madde 5 (2) b"), `refs`, `define`
(tanım), `obligations` (bir aktörün yükümlülükleri), `impact` (bir birimi değiştirmek neyi etkiler).

## 4.5 Vektörler ve kavram eşleştirme
Doküman aranabilir olduktan sonra arka planda:
1. Pasaj vektörleri toplu hâlde çıkarılır (`BRAIN_EMBED_BATCH`, `BRAIN_EMBED_PARALLEL`).
2. Kavram adları embed edilir; anlamı aynı olan kavramlar **eş anlamlı** olarak birleştirilir: "iade onayı" =
   "Refund Approval" (`BRAIN_CONCEPT_SIM`).
3. Kavramlar, saklanmış kod vektörleri üzerinden **onları gerçekleştiren koda** bağlanır (ek API çağrısı yok).

**Vektör önbelleği** her embedding'i model + metin başına bir kez saklar (`data/vectors.db`). Yeniden indeksleme,
aynı dosyanın tekrar yüklenmesi veya yeni bir sürüm yalnızca gerçekten değişen metinler için API çağırır.
`BRAIN_VECTOR_CACHE_DAYS` (180) gün kullanılmayan kayıtlar silinir.

Arama sırasında soru tek bir kez embed edilir ve en fazla `BRAIN_EMBED_BUDGET` (3 sn) beklenir. Gecikirse arama
anahtar kelime, kavram ve graflarla cevap verir; geç gelen vektör bir sonraki arama için saklanır.

## 4.6 Resimler, görsel model ve OCR
Her resim pasajına bir metin verilir. Sıra, en eski resimden başlayarak şöyledir:

1. **Önbellek:** aynı resim (aynı baytlar, SHA-1) daha önce açıklandıysa, hangi dokümanda olursa olsun, açıklama
   tekrar kullanılır. API çağrısı yok.
2. **Süs filtresi:** kenarı `BRAIN_PICTURE_MIN_PX` (120 piksel) değerinden küçük veya neredeyse tek renk resimler
   (logo, çizgi, boşluk) atlanır.
3. **Görsel model** (`BRAIN_VLM_MODEL`): resim en fazla 1600 piksel JPEG olarak gönderilir; tüm yazılar ve
   grafiğin/diyagramın gösterdiği şey açıklanır. Saatte en fazla `BRAIN_VLM_MAX_PER_HOUR` (60) çağrı, her biri en
   fazla `BRAIN_VLM_TIMEOUT` (90 sn).
4. **OCR yedeği:** görsel model yoksa, çağrı hata verirse veya zaman aşımına uğrarsa ya da saatlik bütçe dolarsa,
   yerel OCR (RapidOCR, CPU, resim başına ~2 sn) resimdeki yazıyı hemen okur. Görsel model sonra cevap verdiğinde
   OCR metninin yerine kendi açıklamasını yazar.

Bekleyen işler her 10 dakikada bir kendiliğinden devam eder. Örnek: 300 sayfalık taranmış bir PDF, OCR ile
dakikalar içinde aranabilir olur; görsel model saatte 60 sayfa hızıyla arka planda açıklar.

OCR hakkında dürüst notlar:
- isteğe bağlı bir pakettir (`wheels/ocr/`, ~150 MB); kurulu değilse sistem eskisi gibi yalnızca görsel modeli
  kullanır; `BRAIN_OCR=off` ile kapatılır;
- Türkçe harflerin aksanlarını kaybeder (ğ → g); arama aksanları zaten yok saydığı için bulunabilirlik etkilenmez;
- kötü taramalarda satır kaçırabilir ve yalnızca yazıyı okur, grafiğin ne gösterdiğini anlatmaz. Bu yüzden bir
  **taban**dır, görsel modelin yerini tutmaz.

## 4.7 Arayüzdeki Documents sayfası
- Dosya sürükle-bırak, not ekleme;
- doküman başına pasaj, vektör, kural ve açıklanmış resim sayıları (canlı güncellenir);
- *Markdown*, *Card* (doküman kartı), *Outline* (madde ağacı), *Themes* (dokümanlar arası temalar);
- *Memory* paneli (karar hafızası);
- *Remove* ve *Re-index all*.

## 4.8 Arama sonucu
Bir doküman araması pasajları (kaynak, tür, neden eşleştiği, benzerlik), içlerindeki kuralları ve sınırları,
kavramları (tanım ve eş anlamlılarıyla) ve olguları (iki kavramı birlikte anan cümleler) döndürür. Kavram
listesi, sorudaki kavramlardan başlayan bir **Kişiselleştirilmiş PageRank** ile genişletilir; böylece soruyla tek
kelime ortak olmayan ama ortak bir kavramla bağlı pasajlar da bulunur.
