# Teste de qualidade — Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8

vLLM `0.19.1`, gabarito `2026-11-04`, início 2026-11-04T15:25:27.355468+00:00, 50 perguntas (49 na nota automática). Parâmetros: `{"temperature": 0, "top_p": 1, "repetition_penalty": 1.0, "chat_template_kwargs": {"enable_thinking": false}}`.

| Medida | Resultado |
|---|---|
| Etapa 1 — formato (`tool_calls` válido) | 45/49 = 92 % (IC 95 %: 81-97 %) |
| Etapa 1 — indicadores certos | 45/49 = 92 % (IC 95 %: 81-97 %) |
| Etapa 1 — datas certas | 45/49 = 92 % (IC 95 %: 81-97 %) |
| **Etapa 1 — consulta certa** (formato + indicadores + datas, aproximada) | **45/49 = 92 % (IC 95 %: 81-97 %)** |
| **Etapa 2 — resposta certa** (com os dados certos) | **48/49 = 98 % (IC 95 %: 89-100 %)** |
| As duas certas | 44/49 = 90 % (IC 95 %: 78-96 %) |
| Latência etapa 1 (1 usuário) | p50 2.17 s, p95 4.16 s, máx 6.13 s |
| Latência etapa 2 (1 usuário) | p50 1.41 s, p95 4.30 s, máx 4.91 s |
| Latência por pergunta (1 + 2, sem o SQL) | p50 3.62 s, p95 6.75 s, máx 10.38 s |
| *Tokens* gerados na etapa 2 | média 72, máx 206 |

## Por categoria

| Categoria | n | Etapa 1 | Etapa 2 |
|---|---|---|---|
| faixas_valor | 9 | 9 | 9 |
| inadimplencia | 9 | 8 | 9 |
| juros | 4 | 1 | 4 |
| prazos | 6 | 6 | 6 |
| regioes | 16 | 16 | 16 |
| saldo_recursos_livres | 5 | 5 | 4 |

## Falhas (revisar à mão: a etapa 1 é aproximada)

| ID | Etapa | Motivo | SQL ou resposta |
|---|---|---|---|
| 3 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 4 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 41 | etapa 2 | faltam: variação % = 33.2822 | O saldo de crédito com recursos livres das microempresas variou de R$ 43.641,70 milhões em 01/01/2021 para R$ 58.166,60 milhões em 01/01/2023. Isso representa um aumento de 33,30% no período. |
| 45 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 49 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 50 | revisão manual | não existe indicador por região E faixa; a resposta certa é dizer que a base não | O saldo de crédito das EPP (Empresas de Pequeno Porte) do Sudeste, na faixa acima de R$ 100 mil, em 01/10/2022, era de R$ 207.578,50 milhões. |

## Alerta: números sem lastro na resposta (podem ser contas legítimas)

| ID | Números | Resposta |
|---|---|---|
| 36 | 1342.6, 1700.6, 1010.6 | O saldo de crédito das EPP (Empresas de Pequeno Porte) na região Sul evoluiu trimestralmente em 2019 conforme abaixo:  - De janeiro para abril: de R$ 33.530,40  |
| 41 | 33.3 | O saldo de crédito com recursos livres das microempresas variou de R$ 43.641,70 milhões em 01/01/2021 para R$ 58.166,60 milhões em 01/01/2023. Isso representa u |
| 45 | 100 | A taxa de juros para antecipação de fatura de cartão de crédito para empresas de pequeno porte (EPP) reduziu de 33,4% em 01/01/2018 para 16,6% em 01/01/2020. A  |
