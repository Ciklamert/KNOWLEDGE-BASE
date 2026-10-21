# AI-BRAIN — Türkçe dokümantasyon

AI-BRAIN, internete kapalı (air-gapped) bir kurum ağında yazılım ekipleri için çalışan bir **bilgi tabanıdır**.
Kodu ve iş dokümanlarını (kurallar, şartnameler, kararlar, prosedürler) tek bir yerde toplar. Hem insanlar (web
arayüzü) hem de yapay zekâ kodlama ajanları (Claude Code, opencode, pi, Cursor ...) bu bilgiyi kullanır.

Tek dış bağlantısı kurumun **OpenAI uyumlu API**'si (sohbet, embedding, isteğe bağlı görsel model) ve git
sunucularıdır (GitLab, TFS / Azure DevOps Server).

## Bir bakışta

```
 Yapay zekâ ajanları         Tarayıcılar (giriş)        GitLab / TFS
   │ MCP /mcp  │ REST /api        │ /                     │ /webhooks
   ▼           ▼                  ▼                       ▼
 ┌────────── brain serve: tek süreç, tek port (varsayılan 8765) ──────────┐
 │ giriş ve tokenlar · arka plan işleri · ayarlar (.env) · repolar        │
 │                                                                        │
 │ arama ──┬─► kod grafiği + kod vektörleri ─► codebase-memory-mcp        │
 │ sor     │                                                              │
 │ prompt  ├─► çok dilli kod vektörleri (kurumsal embedding)              │
 │ iyileştir                                                              │
 │ gereksinim ─► doküman grafiği (yerleşik motor, SQLite, model çağrısı yok)│
 └───────────────────────────────┬────────────────────────────────────────┘
                                 ▼
               kurumsal OpenAI uyumlu API (sohbet, embedding, görsel)
```

## Bölümler

| # | Belge | Ne anlatır |
|---|---|---|
| 1 | [01-KURULUM.md](01-KURULUM.md) | Windows ve Linux'ta adım adım kurulum, `.env`, kontrol, başlatma |
| 2 | [02-GENEL-MIMARI.md](02-GENEL-MIMARI.md) | Sistem nasıl çalışır: parçalar, veri akışı, depolama, tasarım ilkeleri |
| 3 | [03-REPOLAR-VE-KOD-GRAFIGI.md](03-REPOLAR-VE-KOD-GRAFIGI.md) | Repolar, setler, ana dallar, güncellemeler, webhook'lar, dal katmanları |
| 4 | [04-DOKUMAN-MOTORU.md](04-DOKUMAN-MOTORU.md) | Dokümanların işlenmesi: Markdown, pasajlar, kavramlar, kurallar, resimler, OCR |
| 5 | [05-ARAMA-SOR-IYILESTIR.md](05-ARAMA-SOR-IYILESTIR.md) | Arama, sor, prompt iyileştirme, etki analizi, karar hafızası, gereksinim yazıcı |
| 6 | [06-AJANLAR-API-CLI.md](06-AJANLAR-API-CLI.md) | MCP, REST API ve komut satırı; ajanların bağlanması |
| 7 | [07-AYARLAR-VE-ISLETIM.md](07-AYARLAR-VE-ISLETIM.md) | Ayarlar, yavaş API ayarı, güvenlik, yedekleme, sorun giderme, testler |

Ayrıntılı İngilizce başvuru belgeleri bir üst klasördedir ([../](../02-INSTALLATION.md)); kurulumun web sayfası
hâli [INSTALL.html](../../INSTALL.html) dosyasıdır. Her ayarın tam listesi
[03-CONFIGURATION.md](../03-CONFIGURATION.md) dosyasındadır (ayar adları her dilde aynıdır).

## Temel kavramlar (sözlük)

| Terim | Anlamı |
|---|---|
| **Kod grafiği** | Repodaki semboller (fonksiyon, sınıf, metot) ve aralarındaki ilişkiler: çağırır, kalıtır, route'a bağlanır, test eder. |
| **Kod vektörü** | Bir kod parçasının "anlamını" temsil eden sayı dizisi. Türkçe bir soru ile İngilizce kodun eşleşmesini sağlar. |
| **Doküman grafiği** | Dokümanların pasajları, kavramları, kuralları, maddeleri ve birbirine atıfları. |
| **Embedding** | Bir metni vektöre çeviren model çağrısı (`/embeddings`). |
| **Ana dal** | Kod grafiğinin izlediği dal (`main`). Bir repoda birden fazla ana dal olabilir (`develop`, `release/2.0`). |
| **Dal katmanı (overlay)** | Bir dalın ayrıca indekslenmiş kopyası; o dalla yapılan aramalarda ana dalın yerine geçer. |
| **Set** | Birlikte aranan repo grubu (örneğin `odeme` seti). |
| **Webhook** | GitLab/TFS'in bir birleştirme veya push olduğunda AI-BRAIN'e gönderdiği bildirim. |
| **MCP** | Yapay zekâ ajanlarının araç kullanmak için konuştuğu protokol. |
