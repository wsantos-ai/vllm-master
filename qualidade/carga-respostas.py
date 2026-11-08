# Teste de carga com as perguntas da aplicação: N usuários simultâneos, cada um fazendo as duas etapas de uma
# pergunta (consulta + resposta) e passando à próxima. Só biblioteca padrão; roda no pod, ao lado de
# coletar_respostas.py e pontuar_respostas.py (mesma pasta; nomes com "_" para o import).
#   python3 carga_respostas.py <gabarito.json> [--url ...] [--variante enum-required] [--niveis "1 8 16 32"]
#       -> JSON Lines em stdout: meta, uma linha por pergunta, métricas do servidor no início e no fim de
#          cada nível e amostras a cada 2 s. Progresso em stderr.
#   python3 carga_respostas.py <gabarito.json> --resumo <carga.jsonl>  -> relatório em Markdown
#
# Por nível N: a fila tem as 50 perguntas repetidas R vezes (R = 1 com N = 1; senão ceil(6N/50)), e N
# usuários tiram perguntas da fila até ela esvaziar. Antes do 1º nível, 4 perguntas de aquecimento com 4
# usuários (fora da conta; compilam a gramática do "required"). Vazão contada na janela estável: do início do
# nível até o 1º usuário encontrar a fila vazia (depois disso a concorrência cai).
# Métricas do servidor: lê /metrics sem fixar nomes; soma por nome as séries cujo nome contém
# "preempt", "prefix_cache" (contadores: diferença no nível), "kv_cache_usage" e "num_requests_waiting"
# (máximo das amostras). Sem /metrics, o relatório diz "não lido".
import argparse, json, math, queue, re, statistics, sys, threading, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coletar_respostas as col  # noqa: E402
import pontuar_respostas as pon  # noqa: E402

TROCA = threading.Lock()

def emitir(o):
    with TROCA:
        print(json.dumps(o, ensure_ascii=False), flush=True)

def ler_metricas(base):
    try:
        with urllib.request.urlopen(base + "/metrics", timeout=10) as r:
            texto = r.read().decode("utf-8", "replace")
    except Exception as e:
        return {"_erro": f"{type(e).__name__}: {e}"}
    soma = {}
    for ln in texto.splitlines():
        if ln.startswith("#") or not ln.strip():
            continue
        m = re.match(r"^([A-Za-z_:][\w:]*)(\{[^}]*\})?\s+(\S+)", ln)
        if not m:
            continue
        nome = m.group(1)
        if not re.search(r"preempt|prefix_cache|kv_cache_usage|num_requests_waiting|num_requests_running", nome):
            continue
        if nome.endswith(("_bucket", "_created")):
            continue
        try:
            soma[nome] = soma.get(nome, 0.0) + float(m.group(3))
        except ValueError:
            pass
    return soma

def amostrador(base, nivel, parar):
    while not parar.wait(2.0):
        emitir({"amostra": {"nivel": nivel, "t": time.time(), "m": ler_metricas(base)}})

def nivel(base, modelo, g, pergs, variante, n, reps, rotulo):
    fila = queue.Queue()
    for r in range(reps):
        for p in pergs:
            fila.put((r, p))
    t0 = time.time()
    vazio = []  # instante em que o 1º usuário achou a fila vazia
    feitos = [0]
    total = fila.qsize()
    def usuario(u):
        while True:
            try:
                r, p = fila.get_nowait()
            except queue.Empty:
                with TROCA:
                    if not vazio:
                        vazio.append(time.time())
                return
            ti = time.time()
            e1, e2 = col.perguntar(base, modelo, g, p, variante)
            tf = time.time()
            emitir({"nivel": rotulo, "rep": r, "usuario": u, "id": p["id"], "t_ini": ti, "t_fim": tf,
                    "etapa1": e1, "etapa2": e2})
            with TROCA:
                feitos[0] += 1
                k = feitos[0]
            if k % max(1, total // 10) == 0 or k == total:
                print(f"  nível {rotulo}: {k}/{total} perguntas, {time.time() - t0:.0f} s", file=sys.stderr, flush=True)
    ths = [threading.Thread(target=usuario, args=(u,)) for u in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    return t0, (vazio[0] if vazio else time.time()), time.time()

def coletar(a):
    g = json.load(open(a.gabarito, encoding="utf-8"))
    modelo = col.http(a.url + "/v1/models", timeout=30)["data"][0]["id"]
    col.ajustar_ao_modelo(modelo)
    try:
        versao = col.http(a.url + "/version", timeout=30).get("version")
    except Exception:
        versao = None
    pergs = g["perguntas"]
    niveis = [int(x) for x in a.niveis.split()]
    emitir({"meta": {"modelo": modelo, "vllm": versao, "inicio": datetime.now(timezone.utc).isoformat(),
                     "gabarito_versao": g["versao"], "n": len(pergs), "params": col.PARAMS,
                     "max_tokens": col.MAX_TOK, "id_chamada": col.ID_CHAMADA, "variante": a.variante,
                     "niveis": niveis}})
    print(f"aquecimento: 4 perguntas, 4 usuários", file=sys.stderr, flush=True)
    nivel(a.url, modelo, g, pergs[:4], a.variante, 4, 1, "aquecimento")
    for n in niveis:
        reps = 1 if n == 1 else math.ceil(6 * n / len(pergs))
        print(f"nível {n}: {reps} x {len(pergs)} perguntas, {n} usuários   {datetime.now().strftime('%T')}",
              file=sys.stderr, flush=True)
        emitir({"metricas": {"nivel": n, "fase": "ini", "t": time.time(), "m": ler_metricas(a.url)}})
        parar = threading.Event()
        am = threading.Thread(target=amostrador, args=(a.url, n, parar), daemon=True)
        am.start()
        t0, tv, tf = nivel(a.url, modelo, g, pergs, a.variante, n, reps, n)
        parar.set(); am.join()
        emitir({"metricas": {"nivel": n, "fase": "fim", "t": time.time(), "m": ler_metricas(a.url)}})
        emitir({"janela": {"nivel": n, "usuarios": n, "reps": reps, "t0": t0, "t_vazia": tv, "t_fim": tf}})
    print(f"fim: {datetime.now(timezone.utc).isoformat()}", file=sys.stderr)

# ---------------- resumo ----------------
def pq(xs, f):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(f * (len(xs) - 1))))] if xs else float("nan")

def resumo(a):
    g = json.load(open(a.gabarito, encoding="utf-8"))
    gp = {p["id"]: p for p in g["perguntas"]}
    meta, regs, ini, fim, janelas, amostras = {}, [], {}, {}, {}, {}
    for ln in open(a.resumo, encoding="utf-8"):
        if not ln.strip():
            continue
        o = json.loads(ln)
        if "meta" in o:
            meta = o["meta"]
        elif "metricas" in o:
            m = o["metricas"]
            (ini if m["fase"] == "ini" else fim)[m["nivel"]] = m["m"]
        elif "janela" in o:
            janelas[o["janela"]["nivel"]] = o["janela"]
        elif "amostra" in o:
            amostras.setdefault(o["amostra"]["nivel"], []).append(o["amostra"]["m"])
        elif "nivel" in o and o["nivel"] != "aquecimento":
            regs.append(o)
    out = [f"# Teste de carga — {meta.get('modelo')}", "",
           f"vLLM `{meta.get('vllm')}`, gabarito `{meta.get('gabarito_versao')}`, variante `{meta.get('variante')}`, "
           f"início {meta.get('inicio')}. Cada pergunta = etapa 1 (consulta) + etapa 2 (resposta), em sequência, "
           "sem *streaming*: a latência é até a resposta completa. Vazão na janela estável (todos os usuários ocupados).", "",
           "| Usuários | Perguntas | Janela estável | Perguntas/min | *Tokens* gerados/s | Latência por pergunta p50 / p95 / máx | Etapa 1 p50 / p95 | Etapa 2 p50 / p95 | Erros HTTP |",
           "|---|---|---|---|---|---|---|---|---|"]
    base1 = {}
    qual = []
    for n in sorted(janelas):
        j = janelas[n]
        rs = [r for r in regs if r["nivel"] == n]
        est = [r for r in rs if r["t_fim"] <= j["t_vazia"]]
        dur = j["t_vazia"] - j["t0"]
        tok = sum(((r[e].get("uso") or {}).get("completion_tokens") or 0) for r in est for e in ("etapa1", "etapa2"))
        lat = [r["t_fim"] - r["t_ini"] for r in rs]
        l1 = [r["etapa1"]["latencia_s"] for r in rs]
        l2 = [r["etapa2"]["latencia_s"] for r in rs]
        err = sum(("erro" in r["etapa1"]) + ("erro" in r["etapa2"]) for r in rs)
        out.append(f"| {n} | {len(rs)} | {dur:.0f} s ({len(est)} perguntas) | {60 * len(est) / dur:.1f} | "
                   f"{tok / dur:.1f} | {pq(lat, .5):.2f} / {pq(lat, .95):.2f} / {max(lat):.2f} s | "
                   f"{pq(l1, .5):.2f} / {pq(l1, .95):.2f} s | {pq(l2, .5):.2f} / {pq(l2, .95):.2f} s | {err} |")
        # qualidade: por repetição, com a régua do pontuador
        for rep in sorted({r["rep"] for r in rs}):
            k = dict(s1=0, s2=0, s12=0, n=0, iguais=0)
            for r in rs:
                if r["rep"] != rep or gp[r["id"]]["manual"]:
                    continue
                p = gp[r["id"]]
                e1, e2 = pon.etapa1(p, r), pon.etapa2(p, r)
                s1 = e1["formato"] and e1["indicadores"] and e1["datas"]
                k["n"] += 1; k["s1"] += s1; k["s2"] += e2["ok"]; k["s12"] += s1 and e2["ok"]
                m1 = r["etapa1"].get("mensagem") or {}  # o id da chamada muda a cada requisição: fica de fora
                chave = ([((t.get("function") or {}).get("name"), (t.get("function") or {}).get("arguments"))
                          for t in m1.get("tool_calls") or []], m1.get("content"),
                         (r["etapa2"].get("mensagem") or {}).get("content"))
                if n == min(janelas):
                    base1[r["id"]] = chave
                elif base1.get(r["id"]) == chave:
                    k["iguais"] += 1
            igual = "—" if n == min(janelas) else f"{k['iguais']}/{k['n']}"
            qual.append(f"| {n} | {rep + 1} | {k['s1']}/{k['n']} | {k['s2']}/{k['n']} | {k['s12']}/{k['n']} | {igual} |")
    out += ["", "## Qualidade sob carga (mesma régua do teste de qualidade; ID 50 fora)", "",
            f"| Usuários | Repetição | Consulta certa | Resposta certa | As duas | Idênticas às de {min(janelas) if janelas else '—'} usuário(s) |",
            "|---|---|---|---|---|---|"] + qual
    out += ["", "## Servidor (/metrics; nomes como o vLLM publica, somados por nome)", ""]
    if not ini or all("_erro" in v for v in ini.values()):
        out.append("não lido: " + "; ".join(v.get("_erro", "") for v in ini.values()))
    else:
        nomes = sorted({x for v in list(ini.values()) + list(fim.values()) for x in v if not x.startswith("_")})
        cont = [x for x in nomes if re.search(r"preempt|prefix_cache", x)]
        gaug = sorted({x for v in amostras.values() for m in v for x in m if re.search(r"kv_cache_usage|num_requests_waiting|num_requests_running", x)})
        out += ["| Usuários | " + " | ".join(f"Δ `{x}`" for x in cont) + " | " + " | ".join(f"máx `{x}`" for x in gaug) + " |",
                "|---|" + "---|" * (len(cont) + len(gaug))]
        for n in sorted(janelas):
            d = [fim.get(n, {}).get(x, float("nan")) - ini.get(n, {}).get(x, float("nan")) for x in cont]
            mx = [max((m.get(x, float("nan")) for m in amostras.get(n, [])), default=float("nan")) for x in gaug]
            out.append(f"| {n} | " + " | ".join(f"{v:g}" for v in d) + " | " + " | ".join(f"{v:g}" for v in mx) + " |")
    print("\n".join(out))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gabarito")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--variante", default="enum-required", choices=["sql", "enum", "enum-required"])
    ap.add_argument("--niveis", default="1 8 16 32")
    ap.add_argument("--resumo")
    a = ap.parse_args()
    resumo(a) if a.resumo else coletar(a)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
