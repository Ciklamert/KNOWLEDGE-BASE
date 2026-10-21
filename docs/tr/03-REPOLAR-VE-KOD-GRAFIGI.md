# 3 — Repolar, kod grafiği, ana dallar ve webhook'lar

## 3.1 Repo tanımı (`repos.json` veya Repositories sayfası)

```json
{
  "repos": [
    {"name": "billing", "url": "gitlab:payments/billing", "branch": "main", "mains": ["develop", "release/2.0"]},
    {"name": "portal",  "url": "tfs:Portal/web-portal",   "branch": "master"},
    {"name": "tools",   "path": "D:/src/tools"}
  ],
  "sets": {"odeme": ["billing", "portal"]}
}
```

| Alan | Zorunlu mu | Anlamı |
|---|---|---|
| `name` | evet | Reponun adı; kod grafiği projesi de bu adı taşır |
| `url` | `url` veya `path` | Sunucunun klonlayıp izlediği git adresi; `gitlab:` ve `tfs:` kısaltmaları kullanılabilir |
| `path` | `url` veya `path` | Sunucudaki mevcut bir çalışma kopyası; asla sıfırlanmaz, yalnız temizse ileri sarılır |
| `branch` | hayır (varsayılan `BRAIN_DEFAULT_BRANCH` = `main`) | **Ana dal**: kod grafiğinin izlediği dal |
| `mains` | hayır (varsayılan `BRAIN_OTHER_MAIN_BRANCHES`) | **Diğer ana dallar** (`develop`, `release/2.0` ...) |
| `provider` | hayır | `gitlab`, `tfs`, `git`, `local`; boşsa adresten anlaşılır; webhook formatını belirler |
| `token` | hayır | Yalnızca bu repo sunucusunun genel tokenından farklı bir token isterse |
| `webhook_secret` | otomatik | Her repoya özel webhook anahtarı (ilk kayıtta üretilir) |

**Setler:** birlikte aranan repo grupları. Arama, sor, iyileştir ve gereksinim yazıcı tek bir repoyu ya da bir
seti hedefleyebilir. `all` seti her zaman vardır.

## 3.2 Kod grafiği nasıl oluşur?
Kod grafiğini hazır, açık kaynaklı **codebase-memory-mcp** programı üretir (`bin/` içinde gelir, yerel CPU'da
çalışır, model indirmez). Programlama dillerini ayrıştırır ve şunları çıkarır:
- semboller: fonksiyon, sınıf, metot, değişken, route;
- ilişkiler: çağırır (`CALLS`), HTTP ile çağırır, kalıtır, uygular, override eder, route'u karşılar, test eder;
- BM25 anahtar kelime indeksi ve programın kendi (İngilizce ağırlıklı) kod embedding'i.

Sonraki güncellemelerde yalnızca değişen dosyalar yeniden işlenir. Hız: kabaca 10.000 dosya başına 1–3 dakika.

## 3.3 Çok dilli kod vektörleri
Kod motorunun kendi vektörleri İngilizce ağırlıklıdır; "müşteriye iade nasıl yapılır" sorusu `refund_payment`
fonksiyonunu bulamaz. Bu yüzden AI-BRAIN her sembolün metnini **kurumsal çok dilli embedding modeliyle** (örneğin
bge-m3) ayrıca vektöre çevirir (`data/codevec/`). Arama iki vektör kaynağını birleştirir.

Maliyet kontrolü:
- yalnızca metni değişen semboller yeniden embed edilir;
- **vektör önbelleği** sayesinde daha önce görülmüş bir metin (başka bir dalda veya eski bir sürümde bile) API'ye
  gitmez;
- `BRAIN_CODE_VECTORS=local` ile bu katman tamamen kapatılabilir.

## 3.4 Repo ne zaman güncellenir?

| Tetikleyici | Ne olur |
|---|---|
| Reponun kendi webhook'u veya grup webhook'u | Ana dala birleştirme/push olduğunda saniyeler içinde güncellenir |
| **Yerel yol** reposunda `git pull` (veya ana dala commit) | `BRAIN_WATCH_LOCAL_SECONDS` (30 sn) içinde fark edilir ve güncellenir |
| Herhangi bir geliştirici kopyasında `brain hook` kurulu ise `git pull` | Pull'dan hemen sonra |
| Arayüzde *Update*, CLI `brain sync`, MCP `sync_repo` | Hemen |
| Zamanlayıcı | Her repo en geç `BRAIN_SYNC_INTERVAL_MINUTES` (1440 = 24 saat) içinde bir kez |

## 3.5 Webhook'lar
Her reponun **kendi** webhook adresi vardır: `/webhooks/repo/<ad>`, kendi gizli anahtarıyla (Repositories
sayfasında *Copy URL*, *Copy secret*). İstersen grup düzeyinde tek bir webhook da kullanılabilir
(`/webhooks/gitlab`, `/webhooks/tfs`).

Bir bildirim geldiğinde:
1. Gizli anahtar sabit zamanlı karşılaştırmayla doğrulanır (yanlışsa 401).
2. Repo bulunur (bilinmiyorsa 404).
3. Olay işlenir:
   - **ana dala** birleştirme veya push → repo güncellenir (202);
   - **diğer bir ana dala** (`develop` gibi) push veya birleştirme → o dalın katmanı güncellenir veya oluşturulur;
   - **silinen bir dal** (yeni commit tamamen sıfır: GitLab `after = 0000…0`, TFS `newObjectId = 0000…0`) → o dalın
     katmanı silinir;
   - katmanı olan bir dala push → katman yeniden indekslenir (`BRAIN_BRANCH_UPDATE_ON_PUSH`);
   - diğer her şey → 200 "ignored".

GitLab'da *Push events* **tüm dallar** için açık olmalıdır; aksi hâlde silinen dallar yalnızca bir sonraki repo
güncellemesinde temizlenir. Son 50 bildirim **Repositories → Webhook deliveries** altında görünür.

## 3.6 Birden fazla ana dal
Birçok ekip birden fazla uzun ömürlü dal tutar: üretim için `main`, entegrasyon için `develop`, bakımdaki bir sürüm
için `release/2.0`. Özellik dalları bunlardan herhangi birinden açılır. AI-BRAIN'de:

- **Main branch** sütunu reponun birincil ana dalıdır; reponun kendi kod grafiği onu izler.
- **Other main branches** sütunu (veya `"mains"`) diğer ana dallardır. Hiçbiri yazılmazsa
  `BRAIN_OTHER_MAIN_BRANCHES` kullanılır.
- Her diğer ana dal kalıcı bir **katman** olarak indekslenir (`billing--develop`):
  - her repo güncellemesinde başı ilerlemişse yeniden indekslenir,
  - push/birleştirme webhook'unda hemen güncellenir,
  - **asla süresi dolmaz**,
  - `branch=develop` ile aranır.
- Bir özellik dalı **türediği ana dalla** karşılaştırılır. AI-BRAIN bunu kendisi bulur: dalın, ana dalda olmayan
  commit sayısı (`git rev-list --count origin/<ana>..origin/<dal>`) en küçük olan ana dal. Arayüzde katmanın
  yanında "from develop" yazar. Kayma kontrolü ve `brain drift` bu dala göre ölçer. İstenirse `base` (REST) veya
  `--main develop` (CLI) ile elle verilir.

Vektörler ek maliyet getirmez: ana dallar arasında değişmeyen semboller vektör önbelleğinden gelir.

## 3.7 Dal katmanları (özellik dalları)
Bir geliştirici `feature/x` dalında çalışırken AI-BRAIN ana dalı gösterir. Dal çok farklılaştıysa:

- **Repositories → Index a branch…** (veya `POST /api/repos/<repo>/branches {"branch": "feature/x"}`) dalı bir git
  worktree'ye (`data/worktrees/`) alır ve ayrı bir proje (`<repo>--<dal>`) olarak indeksler.
- `branch=feature/x` ile yapılan her arama, sor ve iyileştir isteği o repo için ana dal yerine katmanı kullanır.
- Grafik yerel CPU'da tüm worktree'den kurulur (doğru çağrı ilişkileri). Vektörlerde yalnızca dalda değişen
  semboller API'ye gider.

**Katmanlar kendiliğinden temizlenir** (üç katman):
1. **Webhook:** dal silinince hemen. GitLab'da "Delete source branch" ile birleştirilen MR'ın kaynak dalı da silinir.
2. **Uzlaştırma:** her repo güncellemesinden sonra `git ls-remote --heads` ile sunucuda olmayan dalların katmanları
   silinir (webhook kaçarsa güvenlik ağı).
3. **Süre dolumu:** `BRAIN_BRANCH_TTL_DAYS` (30) gün indekslenmeyen veya aranmayan katman silinir (0 = asla). Diğer
   ana dallar bunun dışındadır.

Arayüz her katmanın yaşını ve silineceği tarihi gösterir. Elle silme: ✕ düğmesi.

## 3.8 Dal kayması (drift) kontrolü
`brain drift` (geliştiricinin kendi kopyasında), MCP `check_branch`, `POST /api/drift` veya arayüzdeki *Is my
branch behind the knowledge base?*. Model çağrısı yoktur. Sonuç olarak somut öneriler verir:

| Durum | Öneri |
|---|---|
| AI-BRAIN'in indekslediği commit eski | `sync_brain`: şimdi güncelle |
| Dal, ana dalın gerisinde ve iki tarafta değişen dosyalar var | `rebase_now`: önce bu dosyaları çöz |
| Dal geride ama ortak dosya yok | `rebase_safe`: rebase temiz olmalı |
| Geliştirici dosya değiştirmiş | `trust_local_files`: bu dosyalar için yerel kopyaya güven |
| Değişen kodu test eden testler var | `run_tests`: çalıştırılacak testler |
| 10+ dosya değişmiş | `index_branch`: katman oluştur |
| Katman dal başından eski | `refresh_overlay` |

## 3.9 Kod araçları
Ajanlar ve arayüz için, çalışma kopyası gerektirmeden tüm repolarda:
- `symbol`: kaynak, çağıranlar, çağrılanlar tek cevapta;
- `outline`: bir dosyadaki tanımlar ve satır aralıkları;
- `read`: yalnız istenen satırlar;
- `grep`, `files`: metin ve dosya araması;
- `trace`: çağrı zincirleri;
- `overview`: reponun yapısı, route'lar, en çok bağlantılı kod;
- `impact`: bir değişikliğin etkilediği kod, route'lar ve testler.
