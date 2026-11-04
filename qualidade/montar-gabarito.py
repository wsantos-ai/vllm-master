# Gera qualidade/gabarito-qualidade.json a partir de dataset/dataset-test.csv (estação, Python 3.10+).
# Uso: python qualidade/montar-gabarito.py
#
# Por pergunta, o gabarito guarda:
#   alvo       o que o SQL do modelo precisa pedir (indicadores e datas), para a nota da etapa 1;
#   dados      as linhas que a ferramenta devolve na etapa 2, simulando o banco;
#   sql_dados  o SQL que "gerou" essas linhas (vai na chamada de ferramenta simulada);
#   esperados  os números que a resposta da etapa 2 precisa conter;
#   termos     palavras que a resposta precisa conter (perguntas "qual região/faixa");
#   manual     true = fora da nota automática (revisão à mão).
# IDs 1-26 saem do CSV automaticamente; 27-50 estão escritos à mão abaixo, a partir de
# Valor_Identificado e da Resposta do próprio CSV.
import csv, json, re, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CSV = RAIZ / "dataset" / "dataset-test.csv"
SAIDA = RAIZ / "qualidade" / "gabarito-qualidade.json"
TABELA = "[dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F]"

IN_PEQ = "Taxa de inadimplência de pessoa jurídica - pequeno porte"
IN_MIC = "Taxa de inadimplência de pessoa jurídica - microempresa"
JU_PEQ = "Taxa de juros de pessoa jurídica - pequeno porte - recursos livres"
RL_PEQ = "Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total"
RL_MIC = "Saldo de crédito pessoa jurídica por origem dos recursos - microempresa - recursos livres - Total"
def REG(porte, r): return f"Saldo de crédito pessoa jurídica por região - {porte} - {r}"
def PRZ(s): return f"Saldo de crédito de pessoa jurídica por prazo - pequeno porte - {s}"
def FX(s): return f"Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - {s}"
JU_MIC = "Taxa de juros de pessoa jurídica  micro empresa - recursos livres"  # dois espaços, como no CSV
REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
FAIXAS = ["Menor que 1 mil", "De 1 mil a 5 mil", "De 5 mil a 10 mil", "De 10 mil a 50 mil",
          "De 50 mil a 100 mil", "Acima de 100 mil"]
TRIM = ["01-01", "04-01", "07-01", "10-01"]

def linhas(*trios):
    return [{"DT_REGISTRO": d, "NM_INDICADOR": n, "VL_INDICADOR": v} for d, n, v in trios]

def serie(ano, nome, valores):
    return linhas(*[(f"{ano}-{m}", nome, v) for m, v in zip(TRIM, valores)])

def esp(*pares):
    return [{"rotulo": r, "valor": v} for r, v in pares]

# ---- IDs 27-50, escritos à mão (valores de Valor_Identificado; ID 42 da coluna Resposta) ----
M = {}
M[27] = dict(dados=linhas(("2020-01-01", IN_MIC, 10.0), ("2020-01-01", IN_PEQ, 5.0)))
M[28] = dict(dados=linhas(("2022-10-01", REG("pequeno porte", "Nordeste"), 45748.1),
                          ("2022-10-01", REG("pequeno porte", "Centro-Oeste"), 40745.6)), termos=["nordeste"])
M[29] = dict(dados=linhas(("2023-04-01", REG("microempresa", "Sudeste"), 32471.5),
                          ("2023-04-01", REG("microempresa", "Sul"), 17834.4)), termos=["sudeste"])
M[30] = dict(dados=linhas(("2022-10-01", PRZ("maior que 2 a 5 anos"), 202112.6),
                          ("2022-10-01", PRZ("acima de 5 anos"), 81602.5)))
M[31] = dict(dados=linhas(("2023-04-01", RL_PEQ, 313650.4), ("2023-04-01", RL_MIC, 60553.5)))
M[32] = dict(dados=linhas(("2020-07-01", FX("De 10 mil a 50 mil"), 40272.7),
                          ("2020-07-01", FX("De 50 mil a 100 mil"), 38355.4)))
M[33] = dict(dados=serie(2021, IN_PEQ, [3.5, 3.8, 3.8, 4.1]), ano=2021)
M[34] = dict(dados=serie(2022, JU_MIC, [39.9, 37.8, 37.6, 37.0]), ano=2022)
M[35] = dict(dados=serie(2020, REG("microempresa", "Sudeste"), [25881.5, 26739.4, 24032.6, 34145.0]), ano=2020)
M[36] = dict(dados=serie(2019, REG("pequeno porte", "Sul"), [33530.4, 34873.0, 36572.6, 37583.2]), ano=2019)
M[37] = dict(dados=serie(2022, FX("Acima de 100 mil"), [168550.2, 170011.8, 196216.9, 207578.5]), ano=2022)
M[38] = dict(dados=serie(2020, RL_PEQ, [136985.2, 140377.3, 194351.6, 203050.4]), ano=2020)
M[39] = dict(dados=linhas(*[(f"{a}-01-01", IN_PEQ, v) for a, v in
                            zip(range(2019, 2024), [5.9, 5.0, 3.5, 4.1, 5.9])]), anos_jan=[2019, 2023])
M[40] = dict(dados=linhas(("2019-07-01", IN_MIC, 10.2), ("2019-07-01", IN_PEQ, 5.3)),
             extra=esp(("diferença em p.p.", 4.9)))
M[41] = dict(dados=linhas(("2021-01-01", RL_MIC, 43641.7), ("2023-01-01", RL_MIC, 58166.6)),
             extra=esp(("variação %", (58166.6 / 43641.7 - 1) * 100)))
M[42] = dict(dados=linhas(*[("2022-04-01", REG("pequeno porte", r), v) for r, v in
                            zip(REGIOES, [15985.5, 39547.6, 35825.8, 128504.4, 74023.6])]),
             grupo=[REG("pequeno porte", r) for r in REGIOES],
             so=esp(("Sudeste", 128504.4)), termos=["sudeste"])
M[43] = dict(dados=linhas(("2021-10-01", REG("microempresa", "Norte"), 2139.2)), origem="sql_ref",
             grupo=[REG("microempresa", r) for r in REGIOES], termos=["norte"],
             nota="dados = saída do SQL de referência (TOP 1); os outros 4 valores não estão no CSV")
M[44] = dict(dados=linhas(("2023-04-01", PRZ("maior que 2 a 5 anos"), 202159.3),
                          ("2023-04-01", PRZ("até 1 ano"), 33925.9)),
             extra=esp(("diferença R$ milhões", 168233.4)))
M[45] = dict(dados=linhas(("2018-01-01", JU_PEQ, 33.4), ("2020-01-01", JU_PEQ, 16.6)),
             extra=esp(("variação %", (16.6 / 33.4 - 1) * 100)))
M[46] = dict(dados=[{"Maior_Taxa": 10.9, "Menor_Taxa": 2.6}], origem="sql_ref", serie=True,
             indicadores=[IN_PEQ],
             nota="dados = saída do SQL de referência (MAX/MIN, sem datas); a série completa não está no CSV")
M[47] = dict(dados=linhas(("2022-10-01", FX("Acima de 100 mil"), 207578.5)), origem="sql_ref",
             grupo=[FX(f) for f in FAIXAS], termos=["100 mil"],
             nota="dados = saída do SQL de referência (TOP 1); as outras 5 faixas não estão no CSV")
M[48] = dict(dados=serie(2022, IN_MIC, [5.6, 5.4, 5.5, 6.1]), ano=2022, so=esp(("média", 5.65)),
             nota="as 4 linhas vêm da ID 49 (o CSV da 48 só traz a média)")
M[49] = dict(dados=serie(2022, IN_MIC, [5.6, 5.4, 5.5, 6.1]), ano=2022)
M[50] = dict(dados=linhas(("2022-10-01", FX("Acima de 100 mil"), 207578.5)), origem="sql_ref",
             indicadores=[FX("Acima de 100 mil")], manual=True,
             nota="não existe indicador por região E faixa; a resposta certa é dizer que a base não permite "
                  "(coluna Resposta). Revisão à mão")

def br_para_float(s):
    m = re.search(r"\d[\d.]*(?:,\d+)?", s)
    return float(m.group(0).replace(".", "").replace(",", "."))

def iso(d):  # 01/07/2019 -> 2019-07-01
    dd, mm, aa = d.strip().split("/")
    return f"{aa}-{mm}-{dd}"

def sql_canonico(dados):
    nomes = sorted({r["NM_INDICADOR"] for r in dados})
    datas = sorted({r["DT_REGISTRO"] for r in dados})
    q = lambda xs: ", ".join("'" + x.replace("'", "''") + "'" for x in xs)
    return (f"SELECT [DT_REGISTRO], [NM_INDICADOR], [VL_INDICADOR]\nFROM {TABELA}\n"
            f"WHERE [NM_INDICADOR] IN ({q(nomes)})\n  AND [DT_REGISTRO] IN ({q(datas)})\n"
            f"ORDER BY [DT_REGISTRO], [NM_INDICADOR];")

def main():
    rows = [r for r in csv.DictReader(open(CSV, encoding="utf-8-sig"), delimiter=";") if (r["ID"] or "").strip()]
    cat = set()
    for r in rows:
        for col in ("SQL - resposta", "SQL - resposta da data mais recente de cada ano e/ou por categoria"):
            for s in re.findall(r"'((?:Taxa|Saldo)[^'%]+)'", r[col] or ""):
                cat.add(s.strip())
    perguntas = []
    for r in rows:
        i = int(r["ID"])
        p = dict(id=i, pergunta=r["Pergunta"].strip(), categoria=r["Categoria"].strip(), porte=r["Porte"].strip(),
                 valor_identificado=r["Valor_Identificado"].strip(), resposta_referencia=r["Resposta"].strip(),
                 sql_referencia=r["SQL - resposta"].strip())
        if i <= 26:
            data = iso(r["Data_Referencia"])
            s1 = r["SQL - resposta"]
            m = re.search(r"\[NM_INDICADOR\]\s*=\s*'([^']+)'", s1)
            if m:
                nome = m.group(1)
            else:
                pares = re.findall(r"\(\s*'(\d{4}-\d\d-\d\d)'\s*,\s*'([^']+)'\s*\)", s1)
                nomes = [n for d, n in pares if d == data]
                assert len(nomes) == 1, (i, data, pares)
                nome = nomes[0]
            cfg = dict(dados=linhas((data, nome, br_para_float(r["Valor_Identificado"]))))
        else:
            cfg = M[i]
        dados = cfg["dados"]
        if "indicadores" in cfg:
            ind = cfg["indicadores"]
        elif "grupo" in cfg:
            ind = []
        else:
            ind = sorted({d["NM_INDICADOR"] for d in dados})
        alvo = dict(indicadores=ind, grupo=cfg.get("grupo", []))
        if cfg.get("serie"):
            alvo["datas"] = []
        elif "ano" in cfg:
            alvo["ano"] = cfg["ano"]
        elif "anos_jan" in cfg:
            alvo["anos_jan"] = cfg["anos_jan"]
        else:
            alvo["datas"] = sorted({d["DT_REGISTRO"] for d in dados})
        if "so" in cfg:
            esperados = cfg["so"]
        else:
            esperados = []
            for d in dados:
                if "VL_INDICADOR" in d:
                    esperados.append({"rotulo": f'{d["DT_REGISTRO"]} {d["NM_INDICADOR"]}', "valor": d["VL_INDICADOR"]})
                else:
                    esperados += [{"rotulo": k, "valor": v} for k, v in d.items()]
        esperados += cfg.get("extra", [])
        origem = cfg.get("origem", "canonico")
        p.update(alvo=alvo, dados=dados, origem_dados=origem,
                 sql_dados=p["sql_referencia"] if origem == "sql_ref" else sql_canonico(dados),
                 esperados=esperados, termos=cfg.get("termos", []), manual=cfg.get("manual", False),
                 nota=cfg.get("nota", ""))
        for n in ind + alvo["grupo"]:
            assert n in cat, (i, n)
        perguntas.append(p)

    sistema = (
        "Você responde perguntas sobre indicadores de crédito a microempresas e empresas de pequeno porte "
        "publicados pelo Banco Central do Brasil.\n\n"
        f"Os dados estão no SQL Server, na tabela {TABELA}, com as colunas:\n"
        "- [DT_REGISTRO] (date): data da observação. A série é trimestral: dia 1 de janeiro, abril, julho e outubro.\n"
        "- [NM_INDICADOR] (nvarchar): nome do indicador. Use exatamente um dos nomes da lista abaixo.\n"
        "- [VL_INDICADOR] (float): valor. Taxas de inadimplência em % (9.0 significa 9,0%); taxas de juros em % "
        "ao ano; saldos em R$ milhões.\n\n"
        "Indicadores disponíveis:\n" + "\n".join(f"- {n}" for n in sorted(cat)) + "\n\n"
        "Regras:\n"
        "1. Para obter qualquer valor, chame a ferramenta consultar_sql com uma consulta SELECT em T-SQL. "
        "Nunca responda com valores que não vieram de uma consulta.\n"
        "2. Com o resultado em mãos, responda em português do Brasil, em poucas frases, citando a data e o valor "
        "no formato brasileiro (por exemplo: 9,0%; R$ 2.191,50 milhões). Faça as contas pedidas na pergunta.\n"
        "3. Se os dados não permitirem responder, diga isso."
    )
    ferramenta = {"type": "function", "function": {
        "name": "consultar_sql",
        "description": "Executa uma consulta SELECT (T-SQL) no SQL Server e devolve as linhas em JSON.",
        "parameters": {"type": "object", "properties": {"sql": {
            "type": "string", "description": f"Consulta SELECT em T-SQL sobre {TABELA}."}},
            "required": ["sql"]}}}
    g = dict(versao="2026-11-04", fonte="dataset/dataset-test.csv", n_perguntas=len(perguntas),
             n_indicadores=len(cat), sistema=sistema, ferramenta=ferramenta, perguntas=perguntas)
    SAIDA.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{SAIDA}: {len(perguntas)} perguntas, {len(cat)} indicadores no catálogo, "
          f"{sum(p['manual'] for p in perguntas)} para revisão manual, "
          f"{sum(p['origem_dados'] == 'sql_ref' for p in perguntas)} com dados = saída do SQL de referência")

if __name__ == "__main__":
    sys.exit(main())
