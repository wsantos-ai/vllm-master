# Teste de carga — mistralai/Mistral-Nemo-Instruct-2407

vLLM `0.19.1`, gabarito `2026-11-06`, variante `enum-required`, início 2026-11-06T13:11:17.921457+00:00. Cada pergunta = etapa 1 (consulta) + etapa 2 (resposta), em sequência, sem *streaming*: a latência é até a resposta completa. Vazão na janela estável (todos os usuários ocupados).

| Usuários | Perguntas | Janela estável | Perguntas/min | *Tokens* gerados/s | Latência por pergunta p50 / p95 / máx | Etapa 1 p50 / p95 | Etapa 2 p50 / p95 | Erros HTTP |
|---|---|---|---|---|---|---|---|---|
| 1 | 50 | 258 s (50 perguntas) | 11.6 | 25.5 | 4.50 / 9.17 / 9.83 s | 2.46 / 6.93 s | 2.00 / 3.77 s | 0 |
| 8 | 50 | 46 s (43 perguntas) | 55.9 | 114.1 | 6.87 / 11.83 / 14.62 s | 3.83 / 9.66 s | 2.98 / 5.63 s | 0 |
| 16 | 100 | 59 s (85 perguntas) | 86.3 | 179.4 | 8.88 / 14.94 / 19.55 s | 5.01 / 10.13 s | 3.86 / 6.85 s | 0 |
| 32 | 200 | 95 s (169 perguntas) | 106.9 | 225.3 | 14.63 / 24.99 / 32.23 s | 8.29 / 16.79 s | 6.39 / 11.24 s | 0 |

## Qualidade sob carga (mesma régua do teste de qualidade; ID 50 fora)

| Usuários | Repetição | Consulta certa | Resposta certa | As duas | Idênticas às de 1 usuário(s) |
|---|---|---|---|---|---|
| 1 | 1 | 48/49 | 45/49 | 44/49 | — |
| 8 | 1 | 48/49 | 45/49 | 44/49 | 49/49 |
| 16 | 1 | 48/49 | 45/49 | 44/49 | 48/49 |
| 16 | 2 | 48/49 | 45/49 | 44/49 | 49/49 |
| 32 | 1 | 48/49 | 45/49 | 44/49 | 47/49 |
| 32 | 2 | 48/49 | 45/49 | 44/49 | 49/49 |
| 32 | 3 | 48/49 | 45/49 | 44/49 | 48/49 |
| 32 | 4 | 48/49 | 45/49 | 44/49 | 49/49 |

## Servidor (/metrics; nomes como o vLLM publica, somados por nome)

| Usuários | Δ `vllm:external_prefix_cache_hits_total` | Δ `vllm:external_prefix_cache_queries_total` | Δ `vllm:num_preemptions_total` | Δ `vllm:prefix_cache_hits_total` | Δ `vllm:prefix_cache_queries_total` | máx `vllm:kv_cache_usage_perc` | máx `vllm:num_requests_running` | máx `vllm:num_requests_waiting` |
|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 0 | 0 | 203744 | 215741 | 0.089983 | 1 | 0 |
| 8 | 0 | 0 | 0 | 214784 | 215741 | 0.169213 | 8 | 0 |
| 16 | 0 | 0 | 0 | 429568 | 431482 | 0.246746 | 16 | 0 |
| 32 | 0 | 0 | 0 | 859136 | 862964 | 0.34352 | 32 | 0 |
