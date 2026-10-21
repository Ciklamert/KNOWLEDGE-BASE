# 1 — Kurulum (Windows ve Linux)

Kurulum **internet gerektirmez**. Klasörde Python paketleri (`wheels/`) ve kod motoru (`bin/`) hazır gelir. Kurulum
betiği paketleri yalnızca bu klasörden yükler (`pip --no-index`).

## 1.1 Gerekenler

| Gereksinim | Windows | Linux |
|---|---|---|
| İşletim sistemi | Windows 10/11 veya Windows Server 2019+, 64 bit | x86-64, glibc 2.17+ (RHEL/Rocky 8+, Ubuntu 20.04+, Debian 11+) |
| Python | **3.13** (python.org; kurulumda *Add python.exe to PATH* işaretli) | `python3.13` ve `python3.13-venv` |
| git | Git for Windows | `git` paketi |
| Donanım | 4 çekirdek, 8 GB RAM (büyük monorepo için 16 GB), 10 GB disk + kaynak kodun 3 katı | aynı |
| Gelen ağ | Kullanıcılar, ajanlar ve git sunucularından TCP 8765 (değiştirilebilir) | aynı |
| Giden ağ | Yalnızca kurumsal API ve git sunucuları | aynı |
| Kurumsal API | `/v1` ile biten adres, API anahtarı, bir sohbet modeli, bir embedding modeli ve vektör boyutu (bge-m3: 1024); isteğe bağlı görsel model | aynı |

Neden sadece Python 3.13? Tek sürüm = tek test edilmiş paket seti ve küçük bir paket klasörü. Kurulum başka bir
sürüm bulursa açık bir mesajla durur.

## 1.2 Klasörü kopyalayın
- **Windows:** örneğin `D:\AI-BRAIN`. OneDrive gibi eşitleme araçlarının yönettiği bir klasör kullanmayın.
- **Linux:** örneğin `/opt/ai-brain`; sahibi sunucuyu çalıştıracak kullanıcı olsun.

## 1.3 Kurulum betiğini çalıştırın

### Windows
1. Klasörde PowerShell açın (Dosya Gezgini → Shift + sağ tık → *PowerShell penceresini burada aç*).
2. Çalıştırın:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```
3. Betik sırasıyla şunları yapar:
   1. Python 3.13'ü bulur, git yoksa uyarır;
   2. `.venv` sanal ortamını oluşturur (başka sürümle kurulmuşsa yeniden kurar);
   3. `wheels\` içindeki tüm paketleri internetsiz yükler;
   4. **OCR paketi** (`wheels\ocr\`) varsa onu da yükler (isteğe bağlı, bkz. [04](04-DOKUMAN-MOTORU.md) §4.6);
   5. kod motoru arşivinin SHA-256 özetini `bin\SHA256SUMS` ile karşılaştırır, `bin\windows\` içine açar ve bir
      kez çalıştırır;
   6. `.env.example` dosyasından `.env` oluşturur (rastgele `BRAIN_API_TOKEN` ve `BRAIN_SECRET_KEY` ile) ve
      zorunlu değerler için Not Defteri'nde açar; var olan `.env` korunur;
   7. yoksa boş bir `repos.json` oluşturur;
   8. `brain doctor` kontrolünü çalıştırır;
   9. port için Windows Güvenlik Duvarı kuralı ve oturum açılınca sunucuyu başlatan `AI-BRAIN` zamanlanmış görevi
      önerir.
4. Seçenekler: `-NonInteractive` (soru sormaz), `-Python C:\Python313\python.exe`, `-Firewall`, `-Autostart`.

### Linux
```bash
cd /opt/ai-brain && chmod +x setup.sh brain.sh && ./setup.sh
```
Aynı adımlar uygulanır. `.env` ve `repos.json` 600 izniyle oluşur, `.env` `$EDITOR` ile (varsayılan `vi`) açılır.
Zamanlanmış görev yerine systemd kullanıcı servisi `ai-brain` önerilir. Seçenekler: `--non-interactive`,
`--python /usr/bin/python3.13`, `--autostart`.

Kurulum betiği istendiği kadar yeniden çalıştırılabilir: `.env`, `repos.json` ve `data/` korunur.

## 1.4 `.env` dosyasını doldurun

**Zorunlu değerler:**

| Anahtar | Örnek | Anlamı |
|---|---|---|
| `BRAIN_UI_PASSWORD` | güçlü bir parola | Arayüz ve API girişi (kullanıcı `BRAIN_UI_USER`, varsayılan `admin`) |
| `BRAIN_LLM_BASE_URL` | `https://llm-gateway.corp.local/v1` | Kurumsal OpenAI uyumlu API; `/v1` ile bitmeli |
| `BRAIN_LLM_API_KEY` | `sk-…` | API anahtarı |
| `BRAIN_LLM_MODEL` | `qwen3-32b` | Sor, iyileştir, rehber ve gereksinim yazıcının varsayılan sohbet modeli |
| `BRAIN_EMBEDDING_MODEL` | `bge-m3` | Çok dilli embedding modeli (dokümanlar, kod vektörleri, yeniden sıralama) |
| `BRAIN_EMBEDDING_DIM` | `1024` | Vektör boyutu; `brain doctor` gerçek boyutu yazar |

**Sık kullanılanlar:**

| Anahtar | Örnek | Anlamı |
|---|---|---|
| `BRAIN_PUBLIC_URL` | `http://10.0.0.10:8765` | Kullanıcılara, ajanlara ve webhook adreslerinde gösterilen adres |
| `BRAIN_VLM_MODEL` | `qwen2.5-vl-32b` | Dokümanlardaki resim ve taranmış sayfalar için görsel model; yoksa OCR okur |
| `BRAIN_CA_BUNDLE` | `C:\certs\corp-ca.pem` | Kurumsal API'nin iç sertifika otoritesi |
| `BRAIN_GITLAB_URL`, `BRAIN_GITLAB_TOKEN` | `https://gitlab.corp.local` | Kurumsal GitLab ve okuma tokenı; repolar `gitlab:grup/proje` diye yazılabilir |
| `BRAIN_TFS_URL`, `BRAIN_TFS_TOKEN` | `https://tfs.corp.local/tfs/DefaultCollection` | TFS koleksiyonu ve okuma tokenı; repolar `tfs:Proje/repo` diye yazılabilir |
| `BRAIN_GIT_CA_BUNDLE` | `C:\certs\corp-ca.pem` | Git sunucularının iç sertifika otoritesi |

Diğer tüm değerlerin varsayılanı vardır ve sonradan arayüzden değiştirilebilir (**Settings**; git sunucuları ve
webhook'lar için **Repositories** sayfası). Tam liste: [03-CONFIGURATION.md](../03-CONFIGURATION.md).

## 1.5 Kontrol edin
```powershell
.\brain.cmd doctor        # Linux: ./brain.sh doctor
```
Her satır PASS olmalı; WARN satırları ipucudur.

| Mesaj | Çözüm |
|---|---|
| `corporate chat endpoint` / `corporate embedding endpoint` FAIL | Adres (`/v1` ile bitmeli), anahtar, model adları, proxy, `BRAIN_CA_BUNDLE` |
| `dim=768 (BRAIN_EMBEDDING_DIM=1024)` | `BRAIN_EMBEDDING_DIM` değerini yazılan sayı yapın |
| `code engine runs` FAIL | Antivirüs karantinası (bilinen yanlış alarm): `bin\windows\codebase-memory-mcp.exe` dosyasını `bin\SHA256SUMS` içindeki SHA-256 ile izinli listeye ekleyin |
| `python package …` FAIL | Kurulumu yeniden çalıştırın |
| `BRAIN_UI_PASSWORD` FAIL | Parola belirleyin (`BRAIN_HOST=127.0.0.1` değilse zorunlu) |
| `OCR fallback (optional)` WARN | OCR kurulu değil; istenirse `wheels/ocr/` ile kurulumu tekrar çalıştırın |

## 1.6 Başlatın
```powershell
.\brain.cmd serve          # Linux: ./brain.sh serve
```
Her şey hazır olduğunda konsolda `READY: code graph, document graph and the agents ... are up` yazar. Büyük
repoların ilk indekslemesi arka planda sürer. Herhangi bir makineden `http://<sunucu>:8765` adresini açıp giriş
yapın. **Overview** sayfası her bileşeni, her işin ilerlemesini ve hataları gösterir.

## 1.7 Repoları ekleyin
1. Arayüz → **Repositories** → *Add or edit repositories*. Her repo için:
   - **ad**,
   - **sağlayıcı** (boş = otomatik),
   - git **URL** (`gitlab:grup/proje`, `tfs:Proje/repo` veya tam adres; sunucu klonlar) **ya da** sunucudaki
     yerel **yol**,
   - **Main branch**: izlenecek ana dal (boş = `BRAIN_DEFAULT_BRANCH`, yani `main`),
   - **Other main branches**: varsa diğer uzun ömürlü ana dallar, virgülle (`develop, release/2.0`),
   - gerekirse repoya özel token.
2. *Repository sets*: her setin repolarını işaretleyin.
3. **Save repositories and sets**: yeni repolar hemen indekslenir. 10.000 dosyalık bir repo ilk seferde birkaç
   dakika, sonraki güncellemeler saniyeler sürer.

Alternatif: `repos.json` dosyasını doğrudan düzenleyin (örnek: `repos.example.json`).

## 1.8 Dokümanları ekleyin
Arayüz → **Documents** → dosyaları sürükleyip bırakın. Durum *pending* → *processing* → *processed* olur; hata
varsa sebebi yazılır. Doküman yükleme biter bitmez aranabilir.

## 1.9 Webhook'ları bağlayın
**Repositories** sayfasında her reponun kendi webhook adresi, gizli anahtarı ve kurulum adımları vardır:
- **GitLab:** proje → *Settings → Webhooks*; adres, *Secret token*; tetikleyiciler *Merge request events* ve
  **tüm dallar için** *Push events*.
- **TFS:** *Project settings → Service hooks → Web Hooks*; *Pull request merge attempted* ve herhangi bir dal için
  *Code pushed*; Basic auth parolası = gizli anahtar.

Yerel yol (path) repoları webhook istemez: izlenen dal her `git pull` sonrası otomatik yeniden indekslenir.
Ayrıntı: [03](03-REPOLAR-VE-KOD-GRAFIGI.md) §3.4.

## 1.10 Yapay zekâ ajanlarını bağlayın
```bash
brain connect
```
Claude Code, opencode ve pi için adresiniz ve tokenınızla hazır yapılandırmayı yazar. Ayrıntı:
[06](06-AJANLAR-API-CLI.md).

## 1.11 Sürekli çalıştırma
- **Windows:** kurulumdaki *Autostart* (oturum açılınca zamanlanmış görev) veya klasörde
  `.venv\Scripts\python.exe brain.py serve` çalıştıran bir servis sarmalayıcı (NSSM gibi).
- **Linux:** kurulumdaki systemd kullanıcı servisi ve açılışta başlaması için
  `sudo loginctl enable-linger <kullanıcı>`.

## 1.12 HTTPS (isteğe bağlı)
`BRAIN_TLS_CERT` ve `BRAIN_TLS_KEY` (PEM dosyaları) ayarlayıp yeniden başlatın; webhook ve ajan ayarlarında
`https://` kullanın. Ya da önüne bir TLS ters proxy koyup `BRAIN_HOST=127.0.0.1` yapın.

## 1.13 Klasörü küçültmek
- Yalnız Linux kurulumunda `wheels/*win_amd64.whl`, yalnız Windows kurulumunda `wheels/*manylinux*.whl` silinebilir
  (`*-none-any.whl` dosyaları kalmalı). Diğer işletim sisteminin `bin/` arşivi de silinebilir.
- OCR istenmiyorsa `wheels/ocr/` (yaklaşık 150 MB) silinebilir; sistem resimleri yalnızca görsel modelle okur.
