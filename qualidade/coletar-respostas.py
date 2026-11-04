# Coleta as respostas de um servidor vLLM para o teste de qualidade. Só biblioteca padrão (roda no pod).
# Uso: python3 coletar-respostas.py <gabarito.json> [--url http://127.0.0.1:8000] [--ids 1,2,3]
# Saída: JSON Lines em stdout (1ª linha = meta; depois 1 linha por pergunta). Progresso em stderr.
#
# Por pergunta, duas chamadas, uma de cada vez (1 usuário):
#   etapa 1: sistema + pergunta, com a ferramenta consultar_sql -> o modelo deve pedir o SQL;
#   etapa 2: sistema + pergunta + chamada simulada (sql_dados) + resultado simulado (dados)
#            -> o modelo deve responder em texto. Independe do que o modelo fez na etapa 1.
# Amostragem fixada em toda chamada: temperature 0, top_p 1, repetition_penalty 1; raciocínio do
# Qwen3 desligado (chat_template_kwargs.enable_thinking=false; o template dos Qwen2.5 ignora).
import argparse, json, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

PARAMS = {"temperature": 0, "top_p": 1, "repetition_penalty": 1.0,
          "chat_template_kwargs": {"enable_thinking": False}}
MAX_TOK = {"etapa1": 512, "etapa2": 768}

def http(url, corpo=None, timeout=600):
    req = urllib.request.Request(url, json.dumps(corpo).encode() if corpo is not None else None,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def chamar(base, modelo, mensagens, ferramenta, etapa):
    corpo = dict(model=modelo, messages=mensagens, tools=[ferramenta], tool_choice="auto",
                 max_tokens=MAX_TOK[etapa], **PARAMS)
    t0 = time.monotonic()
    try:
        r = http(base + "/v1/chat/completions", corpo)
        ch = r["choices"][0]
        return {"latencia_s": round(time.monotonic() - t0, 3), "mensagem": ch["message"],
                "finish_reason": ch.get("finish_reason"), "uso": r.get("usage")}
    except urllib.error.HTTPError as e:
        return {"latencia_s": round(time.monotonic() - t0, 3), "erro": f"HTTP {e.code}: {e.read().decode()[:2000]}"}
    except Exception as e:  # timeout, conexão
        return {"latencia_s": round(time.monotonic() - t0, 3), "erro": f"{type(e).__name__}: {e}"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gabarito")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--ids", default="")
    a = ap.parse_args()
    g = json.load(open(a.gabarito, encoding="utf-8"))
    modelo = http(a.url + "/v1/models", timeout=30)["data"][0]["id"]
    try:
        versao = http(a.url + "/version", timeout=30).get("version")
    except Exception:
        versao = None
    ids = {int(x) for x in a.ids.split(",") if x.strip()}
    pergs = [p for p in g["perguntas"] if not ids or p["id"] in ids]
    meta = {"meta": {"modelo": modelo, "vllm": versao, "inicio": datetime.now(timezone.utc).isoformat(),
                     "gabarito_versao": g["versao"], "n": len(pergs), "params": PARAMS, "max_tokens": MAX_TOK}}
    print(json.dumps(meta, ensure_ascii=False), flush=True)
    sis = {"role": "system", "content": g["sistema"]}
    for k, p in enumerate(pergs, 1):
        usr = {"role": "user", "content": p["pergunta"]}
        e1 = chamar(a.url, modelo, [sis, usr], g["ferramenta"], "etapa1")
        chamada = {"id": "chamada-1", "type": "function", "function": {
            "name": "consultar_sql", "arguments": json.dumps({"sql": p["sql_dados"]}, ensure_ascii=False)}}
        msgs2 = [sis, usr, {"role": "assistant", "content": None, "tool_calls": [chamada]},
                 {"role": "tool", "tool_call_id": "chamada-1", "content": json.dumps(p["dados"], ensure_ascii=False)}]
        e2 = chamar(a.url, modelo, msgs2, g["ferramenta"], "etapa2")
        print(json.dumps({"id": p["id"], "etapa1": e1, "etapa2": e2}, ensure_ascii=False), flush=True)
        tc = (e1.get("mensagem") or {}).get("tool_calls") or []
        txt = ((e2.get("mensagem") or {}).get("content") or e2.get("erro") or "").replace("\n", " ")
        print(f"[{k:2d}/{len(pergs)}] ID {p['id']:2d}  etapa1: {'tool_call' if tc else 'SEM tool_call'} "
              f"{e1['latencia_s']:.1f} s | etapa2: {e2['latencia_s']:.1f} s  {txt[:90]}", file=sys.stderr, flush=True)
    print(f"fim: {datetime.now(timezone.utc).isoformat()}", file=sys.stderr)

if __name__ == "__main__":
    main()
