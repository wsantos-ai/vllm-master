# Teste de qualidade — Qwen/Qwen2.5-7B-Instruct

vLLM `0.19.1`, gabarito `2026-11-04`, início 2026-11-04T15:13:41.900680+00:00, 50 perguntas (49 na nota automática). Parâmetros: `{"temperature": 0, "top_p": 1, "repetition_penalty": 1.0, "chat_template_kwargs": {"enable_thinking": false}}`.

| Medida | Resultado |
|---|---|
| Etapa 1 — formato (`tool_calls` válido) | 0/49 = 0 % (IC 95 %: 0-7 %) |
| Etapa 1 — indicadores certos | 0/49 = 0 % (IC 95 %: 0-7 %) |
| Etapa 1 — datas certas | 0/49 = 0 % (IC 95 %: 0-7 %) |
| **Etapa 1 — consulta certa** (formato + indicadores + datas, aproximada) | **0/49 = 0 % (IC 95 %: 0-7 %)** |
| **Etapa 2 — resposta certa** (com os dados certos) | **12/49 = 24 % (IC 95 %: 15-38 %)** |
| As duas certas | 0/49 = 0 % (IC 95 %: 0-7 %) |
| Latência etapa 1 (1 usuário) | p50 4.02 s, p95 14.06 s, máx 19.82 s |
| Latência etapa 2 (1 usuário) | p50 1.67 s, p95 4.71 s, máx 21.29 s |
| Latência por pergunta (1 + 2, sem o SQL) | p50 7.85 s, p95 18.17 s, máx 24.26 s |
| *Tokens* gerados na etapa 2 | média 99, máx 768 |

## Por categoria

| Categoria | n | Etapa 1 | Etapa 2 |
|---|---|---|---|
| faixas_valor | 9 | 0 | 2 |
| inadimplencia | 9 | 0 | 3 |
| juros | 4 | 0 | 0 |
| prazos | 6 | 0 | 0 |
| regioes | 16 | 0 | 6 |
| saldo_recursos_livres | 5 | 0 | 1 |

## Falhas (revisar à mão: a etapa 1 é aproximada)

| ID | Etapa | Motivo | SQL ou resposta |
|---|---|---|---|
| 1 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 1 | etapa 2 | pediu nova consulta em vez de responder |  |
| 2 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 2 | etapa 2 | pediu nova consulta em vez de responder |  |
| 3 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 3 | etapa 2 | pediu nova consulta em vez de responder |  |
| 4 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 4 | etapa 2 | pediu nova consulta em vez de responder |  |
| 5 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 6 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 7 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 7 | etapa 2 | faltam: 2020-04-01 Saldo de crédito pessoa jurídica por região - pequeno porte - Sudeste = 76403.9 | O saldo de crédito das empresas de pequeno porte do Sudeste no primeiro dia de abril de 2020 era de R$ 76,403,900. |
| 8 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 8 | etapa 2 | faltam: 2017-10-01 Saldo de crédito pessoa jurídica por região - pequeno porte - Norte = 5768.9 | O saldo de crédito das pessoas jurídicas de pequeno porte da região Norte no dia 01/10/2017 foi de R$ 5,768,900. |
| 9 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 9 | etapa 2 | faltam: 2022-07-01 Saldo de crédito pessoa jurídica por região - pequeno porte - Nordeste = 43893.8 | As empresas de pequeno porte do Nordeste tinham um saldo de crédito de R$ 43,893,800.00 em 01/07/2022. |
| 10 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 11 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 11 | etapa 2 | faltam: 2019-10-01 Saldo de crédito pessoa jurídica por origem dos recursos - microempresa - recursos livres - Total = 46853.8 | O saldo de crédito com recursos livres das microempresas em 01/10/2019 foi de R$ 468,53. |
| 12 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 12 | etapa 2 | faltam: 2021-04-01 Saldo de crédito pessoa jurídica por região - microempresa - Sul = 14251.3 | O saldo de crédito das microempresas da região Sul no dia 01/04/2021 era de R$ 14,251,300. |
| 13 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 14 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 15 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 16 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 16 | etapa 2 | faltam: 2022-04-01 Saldo de crédito pessoa jurídica por região - microempresa - Centro-Oeste = 10493.1 | O saldo de crédito das microempresas do Centro-Oeste em 01/04/2022 era de R$ 10,493,100. |
| 17 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 17 | etapa 2 | faltam: 2014-01-01 Saldo de crédito de pessoa jurídica por prazo - pequeno porte - acima de 5 anos = 50340.8 | O saldo de crédito de empresas de pequeno porte com prazo acima de 5 anos no dia 01/01/2014 foi de R$ 503,40. |
| 18 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 18 | etapa 2 | faltam: 2016-07-01 Saldo de crédito de pessoa jurídica por prazo - pequeno porte - até 1 ano = 22530.7 | O saldo de crédito de crédito das empresas de pequeno porte com prazo de até 1 ano no dia 01/07/2016 era de R$ 225,30. |
| 19 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 19 | etapa 2 | faltam: 2019-10-01 Saldo de crédito de pessoa jurídica por prazo - pequeno porte - maior que 1 a 2 anos = 13004.1 | O saldo de crédito de crédito das empresas de pequeno porte com prazo maior que 1 ano e até 2 anos no dia 1 de outubro de 2019 foi de R$ 13,004,130. |
| 20 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 20 | etapa 2 | faltam: 2020-07-01 Saldo de crédito de pessoa jurídica por prazo - pequeno porte - maior que 2 a 5 anos = 127939 | O saldo de crédito de crédito das empresas de pequeno porte com prazo maior que 2 e até 5 anos em 01/07/2020 foi de R$ 127,938,800. |
| 21 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 21 | etapa 2 | faltam: 2018-04-01 Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - Menor que 1 mil = 2191.5 | O saldo de crédito de empresas de pequeno porte na faixa menor que R$ 1 mil no dia 01/04/2018 foi de R$ 2.191.500. |
| 22 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 23 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 24 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 24 | etapa 2 | faltam: 2022-04-01 Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - De 10 mil a 50 mil = 54552.8 | O saldo de crédito das empresas de pequeno porte na faixa de R$ 10 mil a R$ 50 mil em 01/04/2022 foi de R$ 545,528. |
| 25 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 25 | etapa 2 | faltam: 2021-10-01 Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - De 50 mil a 100 mil = 52971.3 | O saldo de crédito de crédito das empresas de pequeno porte na faixa de R$ 50 mil a R$ 100 mil em 01/10/2021 foi de R$ 529,713 mil. |
| 26 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 26 | etapa 2 | faltam: 2022-10-01 Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - Acima de 100 mil = 207578 | O saldo de crédito das empresas de pequeno porte na faixa acima de R$ 100 mil em 01/10/2022 foi de R$ 207,578,500. |
| 27 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 27 | etapa 2 | pediu nova consulta em vez de responder |  |
| 28 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 28 | etapa 2 | faltam: 2022-10-01 Saldo de crédito pessoa jurídica por região - pequeno porte - Nordeste = 45748.1; 2022-10-01 Saldo de crédito pessoa jurídica por região - pe | Saldo de Crédito das EPP do Nordeste e do Centro-Oeste em 01/10/2022:  - Nordeste: R$ 45,748,100 - Centro-Oeste: R$ 40,745,600  Diferença: R$ 4,992,500 |
| 29 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 29 | etapa 2 | faltam: Sudeste = 32471.5; termo "sudeste" | O Sul tinha maior saldo de crédito para microempresas em 01/2023, com R$ 32.471.500 contra R$ 17.834.400 para o Sul. |
| 30 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 30 | etapa 2 | pediu nova consulta em vez de responder |  |
| 31 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 31 | etapa 2 | faltam: 2023-04-01 Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total = 313650; 2023-04-01 Saldo de crédito pess | Em 01/04/2023, o saldo de crédito de pessoas jurídicas (EPP) foi de R$ 313,650,400,00, enquanto o saldo de crédito de microempresas foi de R$ 60,553,500,00. Portanto, o saldo de crédito de pessoas jur |
| 32 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 32 | etapa 2 | pediu nova consulta em vez de responder |  |
| 33 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 34 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 34 | etapa 2 | pediu nova consulta em vez de responder |  |
| 35 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 35 | etapa 2 | faltam: 2020-01-01 Saldo de crédito pessoa jurídica por região - microempresa - Sudeste = 25881.5; 2020-04-01 Saldo de crédito pessoa jurídica por região - micr | O saldo de crédito das microempresas do Sudeste apresentou uma tendência de crescimento ao longo do ano, com um pico no quarto trimestre. Veja a evolução ao longo do ano:  - 1º trimestre: R$ 25.881.50 |
| 36 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 36 | etapa 2 | pediu nova consulta em vez de responder |  |
| 37 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 37 | etapa 2 | faltam: 2022-01-01 Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - Acima de 100 mil = 168550; 2022-04-01 Saldo de crédito de pessoa jur | Evolução do Saldo de Crédito das EPP na Faixa Acima de R$ 100 Mil em 2022:  - 01/02/2022: R$ 168,550,000 - 01/04/2022: R$ 170,011,800 - 01/07/2022: R$ 196,216,900 - 01/10/2022: R$ 207,578,500 |
| 38 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 38 | etapa 2 | resposta cortada por max_tokens; faltam: 2020-01-01 Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total = 136985; | Evolução do Saldo de Crédito com Recursos Livres das EPP ao Longo de 2020:  - 01/2020: 136.985.200.00 - 01/2020: 140.377.300.00 - 01/2020: 194.351.600.00 - 01/2020: 203.050.400.00  Evolução: 136.985.2 |
| 39 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 40 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 40 | etapa 2 | pediu nova consulta em vez de responder |  |
| 41 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 41 | etapa 2 | pediu nova consulta em vez de responder |  |
| 42 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 42 | etapa 2 | faltam: Sudeste = 128504; termo "sudeste" | O Norte tinha o maior saldo de crédito para EPP em 01/2022, com um saldo de R$ 15.985.500. |
| 43 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 44 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 44 | etapa 2 | pediu nova consulta em vez de responder |  |
| 45 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 45 | etapa 2 | pediu nova consulta em vez de responder |  |
| 46 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 47 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 47 | etapa 2 | faltam: 2022-10-01 Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - Acima de 100 mil = 207578 | A faixa de valor que apresentou o maior saldo de crédito das EPP em 01/10/2022 foi a acima de 100 mil, com um saldo de R$ 207,578,500. |
| 48 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 48 | etapa 2 | pediu nova consulta em vez de responder |  |
| 49 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 49 | etapa 2 | pediu nova consulta em vez de responder |  |
| 50 | revisão manual | não existe indicador por região E faixa; a resposta certa é dizer que a base não | O saldo de crédito das EPP do Sudeste, na faixa acima de R$ 100 mil, em 01/10/2022 foi de R$ 207,578,500. |

## Alerta: números sem lastro na resposta (podem ser contas legítimas)

| ID | Números | Resposta |
|---|---|---|
| 7 | 76.4039 | O saldo de crédito das empresas de pequeno porte do Sudeste no primeiro dia de abril de 2020 era de R$ 76,403,900. |
| 8 | 5.7689 | O saldo de crédito das pessoas jurídicas de pequeno porte da região Norte no dia 01/10/2017 foi de R$ 5,768,900. |
| 9 | 4.38938e+07, 43.8938 | As empresas de pequeno porte do Nordeste tinham um saldo de crédito de R$ 43,893,800.00 em 01/07/2022. |
| 11 | 468.53 | O saldo de crédito com recursos livres das microempresas em 01/10/2019 foi de R$ 468,53. |
| 12 | 14.2513 | O saldo de crédito das microempresas da região Sul no dia 01/04/2021 era de R$ 14,251,300. |
| 13 | 1 | O saldo de crédito das microempresas do Sudeste no dia 01 de julho de 2018 era de R$ 18,844 bilhões. |
| 16 | 10.4931 | O saldo de crédito das microempresas do Centro-Oeste em 01/04/2022 era de R$ 10,493,100. |
| 17 | 503.4 | O saldo de crédito de empresas de pequeno porte com prazo acima de 5 anos no dia 01/01/2014 foi de R$ 503,40. |
| 18 | 225.3 | O saldo de crédito de crédito das empresas de pequeno porte com prazo de até 1 ano no dia 01/07/2016 era de R$ 225,30. |
| 19 | 13.0041 | O saldo de crédito de crédito das empresas de pequeno porte com prazo maior que 1 ano e até 2 anos no dia 1 de outubro de 2019 foi de R$ 13,004,130. |
| 20 | 127.939 | O saldo de crédito de crédito das empresas de pequeno porte com prazo maior que 2 e até 5 anos em 01/07/2020 foi de R$ 127,938,800. |
| 21 | 2.1915e+06 | O saldo de crédito de empresas de pequeno porte na faixa menor que R$ 1 mil no dia 01/04/2018 foi de R$ 2.191.500. |
| 24 | 545.528 | O saldo de crédito das empresas de pequeno porte na faixa de R$ 10 mil a R$ 50 mil em 01/04/2022 foi de R$ 545,528. |
| 25 | 529.713 | O saldo de crédito de crédito das empresas de pequeno porte na faixa de R$ 50 mil a R$ 100 mil em 01/10/2021 foi de R$ 529,713 mil. |
| 26 | 207.578 | O saldo de crédito das empresas de pequeno porte na faixa acima de R$ 100 mil em 01/10/2022 foi de R$ 207,578,500. |
| 28 | 45.7481, 40.7456, 4.9925 | Saldo de Crédito das EPP do Nordeste e do Centro-Oeste em 01/10/2022:  - Nordeste: R$ 45,748,100 - Centro-Oeste: R$ 40,745,600  Diferença: R$ 4,992,500 |
| 29 | 3.24715e+07, 32.4715, 1.78344e+07, 17.8344 | O Sul tinha maior saldo de crédito para microempresas em 01/2023, com R$ 32.471.500 contra R$ 17.834.400 para o Sul. |
| 31 | 313.65, 60.5535, 518.2 | Em 01/04/2023, o saldo de crédito de pessoas jurídicas (EPP) foi de R$ 313,650,400,00, enquanto o saldo de crédito de microempresas foi de R$ 60,553,500,00. Por |
| 35 | 1, 2.58815e+07, 25.8815, 2, 2.67394e+07, 26.7394 | O saldo de crédito das microempresas do Sudeste apresentou uma tendência de crescimento ao longo do ano, com um pico no quarto trimestre. Veja a evolução ao lon |
| 37 | 168.55, 170.012, 196.217, 207.578 | Evolução do Saldo de Crédito das EPP na Faixa Acima de R$ 100 Mil em 2022:  - 01/02/2022: R$ 168,550,000 - 01/04/2022: R$ 170,011,800 - 01/07/2022: R$ 196,216,9 |
| 38 | 1.36985e+08, 136.985, 1.40377e+08, 140.377, 1.94352e+08, 194.352 | Evolução do Saldo de Crédito com Recursos Livres das EPP ao Longo de 2020:  - 01/2020: 136.985.200.00 - 01/2020: 140.377.300.00 - 01/2020: 194.351.600.00 - 01/2 |
| 42 | 1.59855e+07, 15.9855 | O Norte tinha o maior saldo de crédito para EPP em 01/2022, com um saldo de R$ 15.985.500. |
| 47 | 207.578 | A faixa de valor que apresentou o maior saldo de crédito das EPP em 01/10/2022 foi a acima de 100 mil, com um saldo de R$ 207,578,500. |
| 50 | 207.578 | O saldo de crédito das EPP do Sudeste, na faixa acima de R$ 100 mil, em 01/10/2022 foi de R$ 207,578,500. |
