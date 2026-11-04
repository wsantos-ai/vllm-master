# Dá a nota de uma coleta do teste de qualidade, ou compara duas coletas (controle Ray x 1 GPU).
# Só biblioteca padrão; roda na estação ou no pod.
#   python pontuar-respostas.py <gabarito.json> <respostas.jsonl>              -> relatório em Markdown
#   python pontuar-respostas.py <gabarito.json> <a.jsonl> --comparar <b.jsonl> -> respostas iguais?
#
# Etapa 1 (a consulta), sem banco: a nota é aproximada. Conta como certa se
#   formato:     veio tool_calls com nome consultar_sql e "sql" em JSON válido;
#   indicadores: cada NM_INDICADOR do alvo aparece entre aspas no SQL (maiúsculas/minúsculas iguais;
#                espaços NÃO normalizados, como no banco), ou um LIKE do SQL cobre todos;
#   datas:       cada data do alvo aparece ('AAAA-MM-DD' ou 'AAAAMMDD'); para "ano", as 4 datas
#                trimestrais ou YEAR(...) = ano ou um intervalo que comece no ano; para "anos_jan",
#                o dia 1/1 de cada ano ou MONTH(...) = 1 com os dois anos-limite.
#   Um SQL certo escrito de outro jeito pode ser contado como errado: revise as falhas à mão.
# Etapa 2 (a resposta): certa se cada número esperado aparece no texto, aceitando o arredondamento
#   que o próprio texto mostra (ex.: 10,2 escrito "10%" passa; "R$ 45,7 bilhões" vale 45.700 milhões),
#   e se os termos exigidos aparecem. Números sem lastro (fora dos dados, dos esperados e da pergunta)
#   são só alerta.
import argparse, json, math, re, statistics, sys, unicodedata

def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()

def ler_jsonl(caminho):
    meta, por_id = None, {}
    for ln in open(caminho, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        o = json.loads(ln)
        if "meta" in o:
            meta = o["meta"]
        else:
            por_id[o["id"]] = o
    return meta, por_id

def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0, c - m) * 100, min(1, c + m) * 100)

# ---------------- etapa 1 ----------------
def sqls_da_mensagem(msg):
    """Devolve (formato_ok, motivo, lista de SQLs)."""
    tcs = (msg or {}).get("tool_calls") or []
    if not tcs:
        return False, "sem tool_calls (respondeu em texto)", []
    sqls = []
    for tc in tcs:
        f = tc.get("function") or {}
        if f.get("name") != "consultar_sql":
            return False, f"ferramenta errada: {f.get('name')}", []
        try:
            arg = json.loads(f.get("arguments") or "")
        except json.JSONDecodeError:
            return False, "arguments não é JSON válido", []
        if not isinstance(arg, dict) or not isinstance(arg.get("sql"), str) or not arg["sql"].strip():
            return False, "arguments sem campo sql", []
        sqls.append(arg["sql"])
    return True, "", sqls

def like_para_regex(padrao):
    r = ""
    for ch in padrao:
        r += ".*" if ch == "%" else "." if ch == "_" else re.escape(ch)
    return re.compile("^" + r + "$", re.I | re.S)

def nota_indicadores(sql, alvo):
    literais = [s.lower() for s in re.findall(r"N?'((?:[^']|'')*)'", sql)]
    likes = [like_para_regex(s.replace("''", "'")) for s in re.findall(r"LIKE\s+N?'((?:[^']|'')*)'", sql, re.I)]
    def coberto(nome):
        return nome.lower() in literais or any(rx.match(nome) for rx in likes)
    nomes = alvo["indicadores"] + alvo["grupo"]
    faltam = [n for n in nomes if not coberto(n)]
    return not faltam, ("faltam indicadores: " + "; ".join(faltam)) if faltam else ""

def nota_datas(sql, alvo):
    s = sql.replace("-", "")
    tem = lambda d: d.replace("-", "") in s
    if "datas" in alvo:
        faltam = [d for d in alvo["datas"] if not tem(d)]
        return not faltam, ("faltam datas: " + ", ".join(faltam)) if faltam else ""
    if "ano" in alvo:
        a = alvo["ano"]
        if all(tem(f"{a}-{m}") for m in ("01-01", "04-01", "07-01", "10-01")):
            return True, ""
        if re.search(r"YEAR\s*\(\s*\[?\w*\]?\.?\[?DT_REGISTRO\]?\s*\)\s*(=\s*" + str(a) + r"|IN\s*\([^)]*" + str(a) + ")", sql, re.I):
            return True, ""
        if re.search(r"(>=?|BETWEEN)\s*N?'" + str(a) + r"-?01-?01'", sql, re.I):
            return True, ""
        return False, f"não filtra o ano {a}"
    if "anos_jan" in alvo:
        a0, a1 = alvo["anos_jan"]
        if all(tem(f"{a}-01-01") for a in range(a0, a1 + 1)):
            return True, ""
        if re.search(r"MONTH\s*\(\s*\[?\w*\]?\.?\[?DT_REGISTRO\]?\s*\)\s*=\s*1\b", sql, re.I) and str(a0) in sql and str(a1) in sql:
            return True, ""
        return False, f"não filtra 1º de janeiro de {a0} a {a1}"
    return True, ""

def etapa1(p, r):
    e = r.get("etapa1") or {}
    if "erro" in e:
        return dict(formato=False, indicadores=False, datas=False, motivo="erro HTTP: " + e["erro"][:150], sql="")
    ok, motivo, sqls = sqls_da_mensagem(e.get("mensagem"))
    if not ok:
        return dict(formato=False, indicadores=False, datas=False, motivo=motivo, sql="")
    sql = "\n;\n".join(sqls)
    oi, mi = nota_indicadores(sql, p["alvo"])
    od, md = nota_datas(sql, p["alvo"])
    return dict(formato=True, indicadores=oi, datas=od, motivo="; ".join(x for x in (mi, md) if x), sql=sql)

# ---------------- etapa 2 ----------------
DATAS_RX = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{1,2}/(?:19|20)\d\d\b|\b\d{1,2}/\d{1,2}\b"
                      r"|\b\d{4}-\d\d-\d\d\b|\b(?:19|20)\d\d\b")
NUM_RX = re.compile(r"\d[\d.,]*\d|\d")

def numeros(texto):
    """[(valor, tolerância)] dos números do texto, já em unidades do banco (R$ milhões, %)."""
    t = DATAS_RX.sub(" ", texto)
    out = []
    for m in NUM_RX.finditer(t):
        tok = m.group(0)
        if "," in tok and "." in tok and tok.rfind(".") > tok.rfind(","):  # 45,748.1 (inglês)
            inteiro, dec = tok.replace(",", "").split(".")
        elif "," in tok:                                                    # 45.748,1 ou 9,0
            partes = tok.replace(".", "").split(",")
            inteiro, dec = partes[0], "".join(partes[1:])
        elif "." in tok:
            partes = tok.split(".")
            if all(len(x) == 3 for x in partes[1:]):                       # 45.748 (milhar)
                inteiro, dec = tok.replace(".", ""), ""
            else:                                                          # 4.9 (inglês)
                inteiro, dec = "".join(partes[:-1]), partes[-1]
        else:
            inteiro, dec = tok, ""
        try:
            v = float(inteiro + ("." + dec if dec else ""))
        except ValueError:
            continue
        tol = 0.5 * 10 ** (-len(dec))
        depois = sem_acento(t[m.end():m.end() + 12])
        escala = 1000.0 if re.match(r"\s*(bilh|bi\b)", depois) else 1e6 if re.match(r"\s*(trilh|tri\b)", depois) else 1.0
        out.append((v * escala, tol * escala + 1e-9))
        if v >= 1e7:  # escreveu em reais: 45.748.100.000
            out.append((v / 1e6, 0.5 + 1e-9))
    return out

def bate(valor, nums):
    return any(abs(abs(x) - abs(valor)) <= tol for x, tol in nums)

def etapa2(p, r):
    e = r.get("etapa2") or {}
    if "erro" in e:
        return dict(ok=False, motivo="erro HTTP: " + e["erro"][:150], sem_lastro=[], texto="")
    msg = e.get("mensagem") or {}
    texto = msg.get("content") or ""
    if msg.get("tool_calls"):
        return dict(ok=False, motivo="pediu nova consulta em vez de responder", sem_lastro=[], texto=texto)
    if e.get("finish_reason") == "length":
        motivo_len = "resposta cortada por max_tokens; "
    else:
        motivo_len = ""
    nums = numeros(texto)
    faltam = [x["rotulo"] + f" = {x['valor']:g}" for x in p["esperados"] if not bate(x["valor"], nums)]
    tn = sem_acento(texto)
    faltam += [f'termo "{t}"' for t in p["termos"] if sem_acento(t) not in tn]
    conhecidos = [x["valor"] for x in p["esperados"]]
    for d in p["dados"]:
        conhecidos += [v for v in d.values() if isinstance(v, (int, float))]
    nomes = " ".join(p["alvo"]["indicadores"] + p["alvo"]["grupo"] + [d.get("NM_INDICADOR", "") for d in p["dados"]])
    pnums = [v for v, _ in numeros(p["pergunta"] + " " + nomes)]  # números da pergunta e dos nomes (faixas, prazos)
    sem_lastro = []
    for v, tol in nums:
        if v in pnums or any(abs(abs(v) - abs(c)) <= tol for c in conhecidos):
            continue
        if any(abs(v - c) <= max(tol, 0.051) for c in pnums):
            continue
        sem_lastro.append(round(v, 4))
    ok = not faltam
    return dict(ok=ok, motivo=motivo_len + ("faltam: " + "; ".join(faltam) if faltam else ""),
                sem_lastro=sem_lastro, texto=texto)

# ---------------- relatório ----------------
def pct(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100 * k / n:.0f} % (IC 95 %: {lo:.0f}-{hi:.0f} %)" if n else "—"

def percentis(xs):
    if not xs:
        return "—"
    xs = sorted(xs)
    q = lambda f: xs[min(len(xs) - 1, int(round(f * (len(xs) - 1))))]
    return f"p50 {q(0.5):.2f} s, p95 {q(0.95):.2f} s, máx {xs[-1]:.2f} s"

def relatorio(g, meta, resp):
    pergs = [p for p in g["perguntas"] if p["id"] in resp]
    auto = [p for p in pergs if not p["manual"]]
    linhas, falhas = [], []
    k = dict(fmt=0, ind=0, dat=0, s1=0, s2=0, s12=0)
    lat1, lat2, tok2 = [], [], []
    por_cat = {}
    alerta = []
    for p in pergs:
        r = resp[p["id"]]
        a, b = etapa1(p, r), etapa2(p, r)
        lat1.append(r.get("etapa1", {}).get("latencia_s", 0))
        lat2.append(r.get("etapa2", {}).get("latencia_s", 0))
        u = (r.get("etapa2", {}).get("uso") or {}).get("completion_tokens")
        if u:
            tok2.append(u)
        if b["sem_lastro"]:
            alerta.append(f"| {p['id']} | {', '.join(f'{x:g}' for x in b['sem_lastro'][:6])} | {b['texto'][:160].replace(chr(10), ' ').replace('|', '/')} |")
        if p["manual"]:
            falhas.append(f"| {p['id']} | revisão manual | {p['nota'][:80]} | {b['texto'][:200].replace(chr(10), ' ').replace('|', '/')} |")
            continue
        s1 = a["formato"] and a["indicadores"] and a["datas"]
        k["fmt"] += a["formato"]; k["ind"] += a["indicadores"]; k["dat"] += a["datas"]
        k["s1"] += s1; k["s2"] += b["ok"]; k["s12"] += s1 and b["ok"]
        c = por_cat.setdefault(p["categoria"], [0, 0, 0])
        c[0] += 1; c[1] += s1; c[2] += b["ok"]
        if not s1:
            falhas.append(f"| {p['id']} | etapa 1 | {a['motivo'][:160]} | `{a['sql'][:200].replace(chr(10), ' ').replace('|', '/')}` |")
        if not b["ok"]:
            falhas.append(f"| {p['id']} | etapa 2 | {b['motivo'][:160]} | {b['texto'][:200].replace(chr(10), ' ').replace('|', '/')} |")
    n = len(auto)
    out = [f"# Teste de qualidade — {meta.get('modelo')}", "",
           f"vLLM `{meta.get('vllm')}`, gabarito `{meta.get('gabarito_versao')}`, início {meta.get('inicio')}, "
           f"{len(pergs)} perguntas ({n} na nota automática). Parâmetros: `{json.dumps(meta.get('params'), ensure_ascii=False)}`.", "",
           "| Medida | Resultado |", "|---|---|",
           f"| Etapa 1 — formato (`tool_calls` válido) | {pct(k['fmt'], n)} |",
           f"| Etapa 1 — indicadores certos | {pct(k['ind'], n)} |",
           f"| Etapa 1 — datas certas | {pct(k['dat'], n)} |",
           f"| **Etapa 1 — consulta certa** (formato + indicadores + datas, aproximada) | **{pct(k['s1'], n)}** |",
           f"| **Etapa 2 — resposta certa** (com os dados certos) | **{pct(k['s2'], n)}** |",
           f"| As duas certas | {pct(k['s12'], n)} |",
           f"| Latência etapa 1 (1 usuário) | {percentis(lat1)} |",
           f"| Latência etapa 2 (1 usuário) | {percentis(lat2)} |",
           f"| Latência por pergunta (1 + 2, sem o SQL) | {percentis([x + y for x, y in zip(lat1, lat2)])} |",
           f"| *Tokens* gerados na etapa 2 | média {statistics.mean(tok2):.0f}, máx {max(tok2)} |" if tok2 else "",
           "", "## Por categoria", "", "| Categoria | n | Etapa 1 | Etapa 2 |", "|---|---|---|---|"]
    out += [f"| {c} | {v[0]} | {v[1]} | {v[2]} |" for c, v in sorted(por_cat.items())]
    out += ["", "## Falhas (revisar à mão: a etapa 1 é aproximada)", "", "| ID | Etapa | Motivo | SQL ou resposta |", "|---|---|---|---|"]
    out += falhas or ["| — | — | nenhuma | — |"]
    out += ["", "## Alerta: números sem lastro na resposta (podem ser contas legítimas)", "",
            "| ID | Números | Resposta |", "|---|---|---|"]
    out += alerta or ["| — | nenhum | — |"]
    return "\n".join(x for x in out if x is not None)

def comparar(g, a, b):
    (ma, ra), (mb, rb) = a, b
    ids = sorted(set(ra) & set(rb))
    def sql1(r):
        tcs = ((r.get("etapa1") or {}).get("mensagem") or {}).get("tool_calls") or []
        return json.dumps([(t.get("function") or {}).get("arguments") for t in tcs], ensure_ascii=False)
    txt2 = lambda r: ((r.get("etapa2") or {}).get("mensagem") or {}).get("content") or ""
    i1 = [i for i in ids if sql1(ra[i]) == sql1(rb[i])]
    i2 = [i for i in ids if txt2(ra[i]) == txt2(rb[i])]
    out = [f"# Controle: {ma.get('modelo')} ({ma.get('inicio')}) x {mb.get('modelo')} ({mb.get('inicio')})", "",
           f"- Etapa 1, SQL idêntico: {len(i1)}/{len(ids)}",
           f"- Etapa 2, resposta idêntica: {len(i2)}/{len(ids)}", ""]
    if len(i2) < len(ids):
        out += ["| ID | Etapa 2: primeira diferença (A / B) |", "|---|---|"]
        for i in ids:
            x, y = txt2(ra[i]), txt2(rb[i])
            if x != y:
                j = next((k for k in range(min(len(x), len(y))) if x[k] != y[k]), min(len(x), len(y)))
                out.append(f"| {i} | …{x[max(0, j - 30):j + 50]!r} / …{y[max(0, j - 30):j + 50]!r} |")
    da = {i: etapa2(p, ra[i])["ok"] for p in g["perguntas"] if (i := p["id"]) in ra and i in rb and not p["manual"]}
    db = {i: etapa2(p, rb[i])["ok"] for p in g["perguntas"] if (i := p["id"]) in ra and i in rb and not p["manual"]}
    out += ["", f"- Nota da etapa 2: A {sum(da.values())}/{len(da)}, B {sum(db.values())}/{len(db)}; "
            f"perguntas em que a nota muda: {[i for i in da if da[i] != db[i]] or 'nenhuma'}"]
    return "\n".join(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gabarito")
    ap.add_argument("respostas")
    ap.add_argument("--comparar")
    a = ap.parse_args()
    g = json.load(open(a.gabarito, encoding="utf-8"))
    if a.comparar:
        print(comparar(g, ler_jsonl(a.respostas), ler_jsonl(a.comparar)))
    else:
        meta, resp = ler_jsonl(a.respostas)
        print(relatorio(g, meta or {}, resp))

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
