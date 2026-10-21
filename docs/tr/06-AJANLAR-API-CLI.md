# 6 — Yapay zekâ ajanları (MCP), REST API ve komut satırı

## 6.1 Kimlik doğrulama
- **İnsanlar:** web arayüzünde `BRAIN_UI_USER` / `BRAIN_UI_PASSWORD` ile giriş (oturum çerezi
  `BRAIN_SESSION_HOURS` saat geçerli). 60 saniyede 5 hatalı denemeden sonra bekleme.
- **Ajanlar ve betikler:** `Authorization: Bearer <BRAIN_API_TOKEN>` başlığı veya Basic auth.
- **Webhook'lar:** reponun kendi gizli anahtarı (GitLab `X-Gitlab-Token`, TFS Basic auth parolası).

## 6.2 MCP (Claude Code, opencode, pi, Cursor ...)
Adres: `http(s)://<sunucu>:8765/mcp` (HTTP taşıma). Hazır yapılandırma için:
```bash
brain connect            # veya: brain connect claude | opencode | pi
```
Örnek (Claude Code):
```bash
claude mcp add --transport http --scope user brain http://10.0.0.10:8765/mcp --header "Authorization: Bearer <token>"
```

**Araçlar (18):**

| Araç | Ne işe yarar |
|---|---|
| `search` | Kod ve dokümanlarda birlikte arama (`scope`: all, code, semantic, docs; `detail`: brief, normal, full) |
| `symbol` | Bir sembolün kaynağı, çağıranları ve çağrılanları tek cevapta |
| `outline` | Bir dosyanın tanımları ve satır aralıkları (dosyayı okumadan önce) |
| `read` | Yalnız istenen satırlar (en fazla 400) |
| `grep` | Tüm repolarda metin/regex araması (`mode=files` yalnız dosya listesi) |
| `files` | Glob ile dosya listesi |
| `trace` | Çağrı zincirleri (gelen, giden) |
| `impact` | Bir değişikliğin etkisi ve çalıştırılacak testler |
| `overview` | Repo yapısı, route'lar, giriş noktaları, sıcak noktalar |
| `ask` | Sunucu tarafı ajandan alıntılı cevap |
| `enhance_prompt` | Uygulanabilir prompt (hata, özellik, refactor ...) |
| `write_requirements` | Kurum formatında gereksinimler |
| `check_branch` | Dal kayması raporu ve öneriler |
| `list_repos` | Repolar, dallar, setler, indekslenen commit'ler, katmanlar |
| `doc` | Doküman ağacı: list, outline, unit, refs, define, obligations, impact |
| `remember` / `recall` | Karar hafızası |
| `sync_repo` | Arka planda güncelleme |

Araç listesi bilinçli olarak 6.000 karakterin altında tutulur; ajanın her oturumda harcadığı token azdır.

**Ajanlara öğretmek:** [integrations/AGENTS.brain.md](../../integrations/AGENTS.brain.md) dosyasındaki bloğu
projenin `AGENTS.md` veya `CLAUDE.md` dosyasına ekleyin. Ajan grep/glob/dosya okuma yerine AI-BRAIN araçlarını
kullanır, işe `recall` ile başlar ve iş bitince `remember` ile öğrendiğini kaydeder. Claude Code için ayrıca
`/brain-enhance` komutu vardır ([integrations/claude-code/brain-enhance.md](../../integrations/claude-code/brain-enhance.md)).

## 6.3 REST API
Tüm uç noktalar [06-API.md](../06-API.md) dosyasında, kullanım tarifleri [20-REST-API-GUIDE.md](../20-REST-API-GUIDE.md)
dosyasında (curl ve Python örnekleriyle) anlatılır. Sık kullanılanlar:

```bash
H="Authorization: Bearer $BRAIN_API_TOKEN"
# arama
curl -s -H "$H" -H "Content-Type: application/json" -d '{"query":"iade onayı nerede kontrol ediliyor","detail":"brief"}' \
     "$BRAIN_URL/api/search" | jq -r .markdown
# sembol
curl -s -H "$H" "$BRAIN_URL/api/code/symbol?name=refund_payment" | jq -r .text
# prompt iyileştir
curl -s -H "$H" -H "Content-Type: application/json" -d '{"prompt":"faturaya indirim ekle"}' "$BRAIN_URL/api/enhance" | jq -r .enhanced
# doküman yükle (arka plan işi döner)
curl -s -H "$H" -F "files=@prosedur.docx" "$BRAIN_URL/api/docs/upload"
# dal katmanı (base isteğe bağlı: türediği ana dal)
curl -s -H "$H" -H "Content-Type: application/json" -d '{"branch":"feature/x"}' "$BRAIN_URL/api/repos/billing/branches"
# karar kaydet
curl -s -H "$H" -H "Content-Type: application/json" \
     -d '{"type":"gotcha","title":"İade tekrarları","text":"Üç denemeden sonra durur.","repo":"billing","paths":["src/refund.py"]}' \
     "$BRAIN_URL/api/memory"
```

Uzun işlemler (`/api/docs/upload`, `/api/ask` `async: true` ile, gereksinimler, dal indeksleme) bir `job` kimliği
döndürür; `GET /api/jobs/<id>` ile ilerleme ve sonuç izlenir.

## 6.4 Komut satırı (`brain.cmd` / `brain.sh` / `python brain.py`)
Sunucuda ve `BRAIN_URL` + `BRAIN_API_TOKEN` ayarlı herhangi bir geliştirici makinesinde çalışır:

| Komut | Ne yapar |
|---|---|
| `brain serve` | Sunucuyu başlatır |
| `brain doctor` | Kurulumu kontrol eder (Python, API, kod motoru, paketler, OCR, vektör önbelleği, repolar) |
| `brain search "..."` / `brain ask "..."` / `brain enhance "..." --path .` | Arama, soru, prompt (`--path` ile dal kayması notları) |
| `brain guide "konu"` | Proje rehberi |
| `brain sync [repo]` | Güncelleme |
| `brain drift` | Kendi kopyanızdaki dalın kayma raporu; türediğiniz ana dalı kendisi bulur (`--main develop` ile elle) |
| `brain impact` | Değişikliğinizin etkisi ve çalıştırılacak testler (CI için) |
| `brain hook` | Bu kopyada her `git pull` sonrası AI-BRAIN'i güncelleyen git hook'unu kurar (`--remove` kaldırır) |
| `brain connect` | Ajan yapılandırmasını yazar |
| `brain version` | Sürüm |
