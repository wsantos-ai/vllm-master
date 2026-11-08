# Teste de carga — Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8

vLLM `0.19.1`, gabarito `2026-11-06`, variante `enum-required`, início 2026-11-06T13:32:43.605203+00:00. Cada pergunta = etapa 1 (consulta) + etapa 2 (resposta), em sequência, sem *streaming*: a latência é até a resposta completa. Vazão na janela estável (todos os usuários ocupados).

| Usuários | Perguntas | Janela estável | Perguntas/min | *Tokens* gerados/s | Latência por pergunta p50 / p95 / máx | Etapa 1 p50 / p95 | Etapa 2 p50 / p95 | Erros HTTP |
|---|---|---|---|---|---|---|---|---|
| 1 | 50 | 205 s (50 perguntas) | 14.6 | 39.8 | 3.47 / 6.33 / 10.35 s | 1.98 / 3.56 s | 1.48 / 3.96 s | 0 |
| 8 | 50 | 62 s (43 perguntas) | 41.3 | 102.8 | 9.27 / 17.52 / 27.99 s | 5.41 / 10.25 s | 3.81 / 8.86 s | 0 |
| 16 | 100 | 113 s (85 perguntas) | 45.1 | 113.6 | 16.76 / 30.49 / 52.00 s | 9.91 / 18.10 s | 6.61 / 15.30 s | 0 |
| 32 | 200 | 199 s (169 perguntas) | 51.0 | 131.8 | 30.15 / 56.74 / 93.76 s | 18.05 / 32.55 s | 11.87 / 29.44 s | 0 |

## Qualidade sob carga (mesma régua do teste de qualidade; ID 50 fora)

| Usuários | Repetição | Consulta certa | Resposta certa | As duas | Idênticas às de 1 usuário(s) |
|---|---|---|---|---|---|
| 1 | 1 | 49/49 | 47/49 | 47/49 | — |
| 8 | 1 | 49/49 | 47/49 | 47/49 | 49/49 |
| 16 | 1 | 49/49 | 47/49 | 47/49 | 48/49 |
| 16 | 2 | 49/49 | 47/49 | 47/49 | 48/49 |
| 32 | 1 | 49/49 | 47/49 | 47/49 | 49/49 |
| 32 | 2 | 49/49 | 47/49 | 47/49 | 49/49 |
| 32 | 3 | 49/49 | 47/49 | 47/49 | 49/49 |
| 32 | 4 | 49/49 | 47/49 | 47/49 | 47/49 |

## Servidor (/metrics; nomes como o vLLM publica, somados por nome)

| Usuários | Δ `vllm:external_prefix_cache_hits_total` | Δ `vllm:external_prefix_cache_queries_total` | Δ `vllm:num_preemptions_total` | Δ `vllm:prefix_cache_hits_total` | Δ `vllm:prefix_cache_queries_total` | máx `vllm:kv_cache_usage_perc` | máx `vllm:num_requests_running` | máx `vllm:num_requests_waiting` |
|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 0 | 0 | 228368 | 239945 | 0.0458453 | 1 | 0 |
| 8 | 0 | 0 | 0 | 239168 | 239945 | 0.0859599 | 8 | 0 |
| 16 | 0 | 0 | 0 | 478336 | 479890 | 0.12347 | 16 | 0 |
| 32 | 0 | 0 | 0 | 956672 | 959780 | 0.185465 | 32 | 0 |
