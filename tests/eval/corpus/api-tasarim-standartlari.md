# API Tasarım Standartları
Doküman No: STD-021
Versiyon 1.0
Yürürlük tarihi: 10.01.2026

## 1. Genel kurallar
1) Tüm servisler REST prensiplerine uygun tasarlanmalıdır.
2) API sürümü URL içinde belirtilmelidir, örneğin /v1/payments.
3) Kaynak isimleri çoğul ve küçük harfle yazılmalıdır.

## 2. Hata yönetimi
| HTTP kodu | Kullanım |
|---|---|
| 400 | Geçersiz istek |
| 401 | Kimlik doğrulama başarısız |
| 404 | Kaynak bulunamadı |
| 429 | Hız sınırı aşıldı |

Hata yanıtları code, message ve traceId alanlarını içermelidir.

## 3. Güvenlik
Tüm uç noktalar OAuth 2.0 ile korunmalıdır. Kişisel veri içeren yanıtlar loglanmamalıdır.

## 4. Performans
Liste uç noktaları sayfalama desteklemelidir ve tek istekte en fazla 100 kayıt döndürmelidir.
