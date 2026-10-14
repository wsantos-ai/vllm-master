# B-001 — Concorrência 1 a 64 na V100S, `Qwen/Qwen2.5-7B-Instruct` FP16, vLLM `v0.19.1`

> **Estado: medida sob estrangulamento térmico — não é número do motor** (2026-10-14). O diagnóstico
> B-001b mostrou a GPU a 82 °C com `SW Thermal Slowdown` ativo e *clock* caindo para ~400 MHz (máx. 1597)
> durante a carga ([AC-17](../ESTUDO-DE-CASO.md#ac-17)). Vale como retrato de `sabdiia01` **como está**
> e como prova de que a vazão escala com a concorrência. Os valores absolutos estão subestimados, e a
> medição precisa ser refeita com a refrigeração corrigida (PD-24).

## Ambiente e configuração

| Item | Valor |
|---|---|
| Ficha | F3 do [ESTUDO-DE-CASO.md](../ESTUDO-DE-CASO.md) |
| Nó / GPU | `sabdiia01`, 1 × Tesla V100S-PCIE-32GB, sozinha (só `VLLM::EngineCore` em `nvidia-smi`) |
| Imagem | `vllm/vllm-openai:v0.19.1` |
| Servidor | `vllm serve Qwen/Qwen2.5-7B-Instruct --dtype float16 --max-model-len 8192 --gpu-memory-utilization 0.90 --generation-config vllm` (sem `--enforce-eager`; *CUDA graphs* capturados; *prefix caching* ligado; *attention* Triton) |
| *Pod* | `vllm-conc`, CPU 8 a 16, memória 32 a 64 Gi, `/dev/shm` 8 Gi, `nvidia.com/gpu: 1` |
| *KV cache* | 13,14 GiB = 246.016 *tokens* |
| Gerador | `vllm bench serve` **dentro do mesmo *pod*** (divide a CPU com o servidor), `--base-url http://127.0.0.1:8000 --endpoint /v1/completions --dataset-name random --random-input-len 512 --random-output-len 256 --ignore-eos --temperature 0 --metric-percentiles 50,95,99`, `--seed` = concorrência, `--num-prompts` = 8 × concorrência (mínimo 32) |
| *Warmup* | sim: concorrência 4, 16 requisições, semente 999, descartado |
| Data | 2026-10-14, 17:18 a 18:15 |

## Resultado

| Concorrência | Requisições | Vazão de saída (tok/s) | TTFT p50 / p95 / p99 (ms) | TPOT p50 / p95 / p99 (ms) | ITL p50 / p95 / p99 (ms) | *Tok*/s por usuário (1000/TPOT p50) |
|---|---|---|---|---|---|---|
| 1 | 32 | 10,04 | 695 / 1.065 / 1.138 | 93 / 120 / 121 | 93 / 153 / 153 | 10,7 |
| 4 | 32 | 33,35 | 2.729 / 4.017 / 4.017 | 110 / 121 / 123 | 103 / 170 / 171 | 9,1 |
| 8 | 64 | 57,24 | 4.483 / 7.798 / 8.404 | 121 / 136 / 145 | 111 / 114 / 186 | 8,3 |
| 16 | 128 | 86,66 | 6.161 / 11.626 / 12.046 | 158 / 184 / 196 | 134 / 138 / 825 | 6,3 |
| 32 | 256 | 113,66 | 8.959 / 18.915 / 26.144 | 247 / 272 / 278 | 183 / 192 / 2.960 | 4,1 |
| 64 | 512 | 130,43 | 7.857 / 26.009 / 41.953 | 458 / 476 / 483 | 340 / 2.156 / 2.846 | 2,2 |

Zero falhas e zero preempções em todos os níveis.

Pico de vazão de saída em 1 s (`max_output_tokens_per_s` dos JSON) contra a média do nível:

| Concorrência | 1 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|
| Pico (tok/s) | 25 | 40 | 80 | 128 | 192 | 448 |
| Pico ÷ média | 2,5× | 1,2× | 1,4× | 1,5× | 1,7× | 3,4× |

Evidência: [B-001-concorrencia-sabdiia01-2026-10-14-1718.log](../logs-analysis/B-001-concorrencia-sabdiia01-2026-10-14-1718.log)
e os JSON de cada nível: [c1](../logs-analysis/B-001-qwen25-7b-fp16-c1.json),
[c4](../logs-analysis/B-001-qwen25-7b-fp16-c4.json), [c8](../logs-analysis/B-001-qwen25-7b-fp16-c8.json),
[c16](../logs-analysis/B-001-qwen25-7b-fp16-c16.json), [c32](../logs-analysis/B-001-qwen25-7b-fp16-c32.json),
[c64](../logs-analysis/B-001-qwen25-7b-fp16-c64.json).

## Leitura

- **Escala:** a vazão total sobe 13× de 1 para 64 requisições, sem preempção. O agrupamento do vLLM
  funciona na V100S com modelo em FP16, ao contrário do bitsandbytes (AC-16).
- **Suspeita sobre os valores absolutos:**
  1. 10,7 *tok*/s por usuário com concorrência 1, contra ITL p50 de 29 ms (~34 *tok*/s) no *warmup* de
     minutos antes;
  2. na rodada de concorrência 1, o tempo por requisição subiu de 12 s para 28 s, com requisições
     idênticas em tamanho;
  3. TTFT p50 de 2,7 s com concorrência 4, para *prompts* de 512 *tokens*;
  4. pico de vazão bem acima da média: 25 contra 10 *tok*/s com concorrência 1, e 448 contra 130 com 64.
     O sistema chega a andar mais rápido e alterna com paradas.
  **Confirmado no diagnóstico B-001b: estrangulamento térmico da GPU** (AC-17). Numa rodada de 3 min com
  concorrência 1, o *clock* caiu de 1560 para ~400 MHz e as requisições foram de 5,6 s para 21,8 s. A
  cota de CPU foi descartada: `nr_throttled` subiu de 12 para 13.

## Checklist do CLAUDE.md

- [x] *Warmup*.
- [x] GPU exclusiva.
- [x] Uma variável por vez (concorrência).
- [x] *Prompts* sem repetição entre níveis (semente por nível); *prefix caching* ligado, mas *prompts* aleatórios.
- [x] Sem `--enforce-eager`.
- [x] Amostragem fixada (`--generation-config vllm`, `temperature` 0, `--ignore-eos`).
- [x] Gerador dentro do *pod*: sem rede na latência, mas **divide a CPU com o servidor**.
- [ ] Repetição de cada nível: não feita (uma rodada por nível).
- [ ] **GPU sem estrangulamento térmico durante a carga: FALHOU** (AC-17). Item acrescentado ao checklist depois desta medição.
