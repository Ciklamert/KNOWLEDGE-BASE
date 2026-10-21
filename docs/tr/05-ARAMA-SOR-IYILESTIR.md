# 5 — Arama, sor, prompt iyileştirme ve diğer işlevler

Bütün işlevler aynı **aramayı** kullanır. Arama, web arayüzünde, REST API'de ve MCP'de aynı cevabı verir.

## 5.1 İlk adım: prompt analizi
Her arama, sor ve iyileştir isteği önce metni analiz eder (`brain/query.py`, model yok):
- dil tespiti (Türkçe, İngilizce, karışık);
- **durak kelimeler** atılır ("nasıl", "ve", "nerede", "the" ...; `BRAIN_STOPWORDS_EXTRA` ile kurum jargonu
  eklenir);
- **anahtar terimler** önem sırasıyla çıkarılır (en fazla `BRAIN_QUERY_MAX_TERMS`); kod tanımlayıcıları
  (`chargeCustomer`, `tax_rate`) en başa alınır;
- varyantlar: Türkçe kökler, tanımlayıcı parçaları (`charge`, `Customer`), tırnaklı ifadeler.

Arayüzde yazarken analiz giriş kutusunun altında çipler olarak görünür.

## 5.2 Arama hattı (pipeline)
1. **Paralel getirme:** kod grafiği (BM25 + yapı), iki kod vektör indeksi (yerel ve çok dilli), doküman grafiği.
2. **Tam isim eşleşmesi:** soruda adı geçen semboller doğrudan bulunur ve en üste sabitlenir.
3. **Doküman → kod köprüsü:** dokümanlarda bulunan iş terimleri ek kod arama terimi olur
   (`BRAIN_DOC_BRIDGE`).
4. **Graf genişletme:** en iyi kod sonuçlarının çağıranları, çağrılanları ve üst sınıfları aday olarak eklenir
   (`BRAIN_GRAPH_EXPAND`).
5. **Anlamsal yeniden sıralama:** adaylar, indeksleme sırasında saklanmış vektörlerle soruya benzerliğe göre
   sıralanır; ek API çağrısı yoktur (`BRAIN_RERANK*`).
6. **Kavram → kod:** doküman kavramları onları gerçekleştiren koda bağlanır.
7. **Denge:** bir setteki tek bir repo sonuçları doldurmasın diye repolar dengelenir.

Bir aramanın yaptığı **tek** model çağrısı sorunun embedding'idir ve en fazla `BRAIN_EMBED_BUDGET` saniye
beklenir. Sonuçta kaç sonucun hangi kaynaktan geldiği ("kaynak çipleri"), çalışan aşamalar ve süre gösterilir.

**Ayrıntı seviyesi** (`detail`): `brief` (konum, imza, çağıranlar, neden eşleşti), `normal` (ilk 3 sonucun
kaynağı da), `full` (hepsinin kaynağı). Ajanlar için az token = `brief`.

**Dal:** `branch=feature/x` verilirse o dalın katmanı ana dalın yerine kullanılır.

## 5.3 Sor (Ask)
Sunucu tarafında bir ajan, salt okunur araçlarla (arama, sembol, okuma, grep, iz sürme, doküman) araştırır ve
sorunun dilinde, kod (`repo/yol:satır`) ve doküman alıntılarıyla cevap verir.
- Önce kısa bir model çağrısı soruyu ek arama terimlerine (İngilizce tanımlayıcılar, eş anlamlılar, çeviriler)
  çevirir (`BRAIN_QUERY_EXPANSION`).
- Ardından araç çağıran döngü: en fazla `BRAIN_ASK_MAX_STEPS` tur, toplam `BRAIN_ASK_TIMEOUT` saniye.
- Kurumsal ağ geçidi araç çağırmayı desteklemiyorsa otomatik olarak tek seferlik "bağlamla cevapla" moduna geçer
  (`BRAIN_AGENT_TOOL_CALLING`).
- Arayüz, kullanılan araçları ve kanıtı (**Evidence used**) ile model, süre ve token kullanımını gösterir.

## 5.4 Prompt iyileştir (Enhance prompt)
Her türlü isteği (hata düzeltme, yeni özellik, değişiklik, refactor, inceleme) bir kodlama ajanının doğrudan
uygulayabileceği bir prompta dönüştürür. Tek bir mod vardır; isteğin türünü kendisi anlar:
- **hata için:** hatalı yolu izler ve olası kök nedeni bulur;
- **yeni özellik için:** bugün ne olduğunu, nereye oturacağını ve neyin taklit edileceğini gösterir.

Çıktı bölümleri: görev, mevcut durum, analiz, iş kuralları, etki, plan, kabul kriterleri, kapsam dışı, açık
sorular ve **ajan için notlar** (repo ve dal verilirse dal kayması uyarıları dahil). Model çalışmazsa aramadan
üretilmiş bir yedek prompt döner.

## 5.5 Etki analizi (Impact)
Değiştirilen dosyalar veya semboller verilir; model olmadan döner:
- değişen semboller ve onlara bağlı kod (çağıranlar, kalıtanlar, en fazla `depth` adım);
- oraya ulaşan route'lar;
- çalıştırılacak testler;
- değişen kodu anan iş kuralları ve doküman pasajları.

CI'da: `brain impact` (yerel dalın değişikliklerini kendisi hesaplar).

## 5.6 Karar hafızası (Memory)
Ekiplerin ve ajanların yeniden öğrenmemesi gereken bilgiler: `decision` (ne seçildi, neden), `rule` (iş kuralı),
`gotcha` (tuzak ve kaçınma yolu), `convention` (bu kod tabanında işler nasıl yapılır).
- Tür + başlık kimliktir; aynı konuda yenisi eskisinin yerini alır, eski metinler geçmişte tutulur.
- Her kayıt aynı zamanda bir doküman olur, yani normal aramada da bulunur.
- Kayıtta geçen kod yolları artık yoksa kayıt **bayat** olarak işaretlenir.
- MCP `remember` / `recall`, REST `/api/memory`, Documents → *Memory* paneli.

Ajanlar için kural ([AGENTS.brain.md](../../integrations/AGENTS.brain.md)): işe başlarken `recall`, iş bitince bir
sonraki oturumun bilmesi gerekenleri `remember`.

## 5.7 Gereksinim yazıcı (Requirements)
Sistem gereksinimlerini, yeni bir fikri veya mevcut sistemin bir konusunu, **mevcut kod ve dokümanlarla
karşılaştırılmış** yazılım gereksinimlerine çevirir. Tek bir istek alanı vardır, mod yoktur.
- **Format her zaman kurumun kendisidir:** elle yazılır veya Word/PDF şablonundan yüklenir; en çok kullanılan
  başlık seviyesi bölümleri belirler. Yerleşik bir format yoktur.
- Akış: kanıt (arama) → plan (yetenekler ve yazılacak bölümler) → her yetenek için bir parça → diğer bölümler →
  `FR-?` gibi numaraların sırayla verilmesi → ek. Çıktı `data/srs/output/` içine Markdown olarak yazılır.
- Kurallar ISO/IEC/IEEE 29148'e dayanır: gerekli, tek anlamlı ("hızlı", "kullanıcı dostu" yok), tam, tekil,
  doğrulanabilir.

## 5.8 Bir projeyi öğrenmek (Learn a project)
- **Yapı özeti** (model yok): diller, paketler, giriş noktaları, route'lar, en çok bağlantılı kod.
- **Proje rehberi** (birkaç model çağrısı): proje ne yapar, nasıl kuruludur, ana akışlar, okumaya nereden
  başlanmalı. Yeni katılanlar için.

## 5.9 Graf sayfaları
- **Code graph:** bir sembolün komşuluğu (çağıranlar, çağrılanlar, kalıtım).
- **Document graph:** dokümanlar, kavramlar ve aralarındaki bağlar; eş anlamlılar.
