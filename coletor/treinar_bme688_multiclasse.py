#!/usr/bin/env python3
"""Treinamento exploratório multiclasse de padrões do BME688 (NÃO mede acetona em ppm).

Comandos:
 python3 treinar_bme688.py preparar --pasta dados
 python3 treinar_bme688.py treinar --pasta dados
 python3 treinar_bme688.py prever --arquivo dados/nova.bmespecimen

Formatos aceitos: .bmespecimen exportado do BME AI Studio e .bmerawdata.
Nunca altera arquivos de origem. Dependências: numpy, scikit-learn, joblib.
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

COLS = [f"logR{i}" for i in range(10)] + ["temperatura", "umidade", "pressao"]
# Cada rótulo distinto na coluna "tipo" vira uma classe. O programa não
# interpreta nomes como "cetose alta" como diagnóstico ou concentração química.
IGNORE = {"", "ignorar", "ignore", "descartar"}
ALIASES = {"ambiente": "ar ambiente", "ar": "ar ambiente", "hálito": "halito"}


def normalizar_label(valor):
    import unicodedata
    label = " ".join((valor or "").strip().lower().split())
    if label in IGNORE:
        return None
    # Padroniza somente nomes de controle; demais classes permanecem como no CSV.
    return ALIASES.get(label, label)



def get_rows(doc, ext):
    if ext == ".bmespecimen":
        d = doc["data"]
        cols = {c["key"]: i for i, c in enumerate(d["dataColumns"])}
        require = ["resistance_gassensor", "temperature", "relative_humidity", "pressure", "cycle_step_index", "cycle_id"]
        if any(c not in cols for c in require):
            raise ValueError("Colunas obrigatórias ausentes no specimen")
        rows = d["specimenDataPoints"]
        specimens = {"label_original": d.get("specimenData", {}).get("label", ""), "perfil": tuple((x.get("uid"), x.get("timeBase")) for x in d.get("heaterProfiles", []))}
        return rows, cols, specimens, "cycle_id", "cycle_step_index"
    d = doc["rawDataBody"]
    cols = {c["key"]: i for i, c in enumerate(d["dataColumns"])}
    require = ["resistance_gassensor", "temperature", "relative_humidity", "pressure", "heater_profile_step_index", "scanning_cycle_index"]
    if any(c not in cols for c in require):
        raise ValueError("Colunas obrigatórias ausentes nos dados brutos")
    rows = d["dataBlock"]
    return rows, cols, {"label_original": "", "perfil": tuple((x.get("id"), x.get("timeBase")) for x in doc.get("configBody", {}).get("heaterProfiles", []))}, "scanning_cycle_index", "heater_profile_step_index"


def features_from_file(path):
    with path.open(encoding="utf-8") as f:
        doc = json.load(f)
    rows, cols, meta, cyclekey, stepkey = get_rows(doc, path.suffix.lower())
    groups = defaultdict(dict)
    for row in rows:
        try:
            cyc = str(row[cols[cyclekey]])
            step = int(row[cols[stepkey]])
            gas = float(row[cols["resistance_gassensor"]])
            if not 0 <= step < 10 or not math.isfinite(gas) or gas <= 0:
                continue
            if "error_code" in cols and int(row[cols["error_code"]]) != 0:
                continue
            temp = float(row[cols["temperature"]])
            humid = float(row[cols["relative_humidity"]])
            press = float(row[cols["pressure"]])
            if not all(map(math.isfinite, [temp, humid, press])):
                continue
            if step in groups[cyc]:  # Ambiguidade no ciclo: invalida o ciclo inteiro
                groups[cyc]["duplicado"] = True
            groups[cyc][step] = (gas, temp, humid, press)
        except (TypeError, ValueError, IndexError):
            continue
    extracted = []
    for cycle, steps in groups.items():
        if "duplicado" in steps or len(steps) != 10 or set(steps) != set(range(10)):
            continue
        a = [steps[i] for i in range(10)]
        logs = [math.log10(v[0]) for v in a]
        vec = logs + [float(np.median([v[j] for v in a])) for j in (1, 2, 3)]
        extracted.append((cycle, vec))
    if not extracted:
        raise ValueError("Nenhum ciclo completo (etapas 0 a 9) neste arquivo")
    return extracted, meta


def read_manifest(path):
    out = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                out[row["arquivo"]] = row
    return out


def prepare(folder):
    manifest = folder / "amostras.csv"
    known = read_manifest(manifest)
    files = sorted([*folder.glob("*.bmespecimen"), *folder.glob("*.bmerawdata")])
    with manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["arquivo", "tipo", "observacoes"])
        w.writeheader()
        for path in files:
            label = known.get(path.name, {}).get("tipo", "ignorar")
            note = known.get(path.name, {}).get("observacoes", "")
            try:
                cycles, meta = features_from_file(path)
                print(f"{path.name}: {len(cycles)} ciclos completos; rótulo no arquivo: {meta['label_original']!r}")
            except Exception as exc:
                print(f"ATENÇÃO {path.name}: {exc}")
            w.writerow({"arquivo": path.name, "tipo": label, "observacoes": note})
    print(f"\nEdite {manifest}: use nomes de condições (ex.: ar ambiente, halito basal, halito jejum 8h) ou ignorar.")
    print("Cada arquivo deve corresponder a UMA sessão/amostra independente.")


def build(folder):
    rows = read_manifest(folder / "amostras.csv")
    X, y, g = [], [], []
    files_by_class = defaultdict(set)
    profile_by_file = {}
    for filename, entry in rows.items():
        label = normalizar_label(entry["tipo"])
        if label is None:
            continue
        path = folder / filename
        if not path.exists():
            print(f"AVISO: arquivo ausente {path}")
            continue
        try:
            cycles, meta = features_from_file(path)
        except Exception as exc:
            print(f"AVISO: arquivo ignorado {filename}: {exc}")
            continue
        profile_by_file[filename] = meta["perfil"]
        # Mesmo arquivo repetido no manifesto não é permitido; arquivo é unidade de grupo.
        for cycle, vals in cycles:
            X.append(vals)
            y.append(label)
            g.append(filename)
        files_by_class[label].add(filename)
    if len(set(profile_by_file.values())) > 1:
        raise ValueError("Perfis de aquecimento diferentes detectados. Colete usando apenas um perfil.")
    return np.array(X, dtype=float), np.array(y), np.array(g), files_by_class


def train(folder, output):
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.metrics import classification_report, confusion_matrix
    import joblib

    X, y, groups, counts = build(folder)
    print("Sessões por classe:", {k: len(v) for k, v in counts.items()})
    print("Ciclos completos:", len(X))
    classes = sorted(set(y))
    if len(classes) < 2:
        raise SystemExit("Você precisa de ao menos DUAS classes diferentes na coluna tipo do CSV.")
    print("Classes:", ", ".join(classes))
    model = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                          LogisticRegression(max_iter=2000, class_weight="balanced"))
    # Avaliar apenas quando houver sessões distintas suficientes por classe.
    sufficient = all(len(counts[c]) >= 3 for c in classes)
    if sufficient:
        splitter = GroupShuffleSplit(n_splits=100, test_size=0.3, random_state=42)
        split = next(((tr, te) for tr, te in splitter.split(X, y, groups)
                      if set(y[tr]) == set(classes) and set(y[te]) == set(classes)), None)
        if split:
            tr, te = split
            model.fit(X[tr], y[tr])
            print("\nAvaliação exploratória com arquivos diferentes dos usados no treino:")
            print(classification_report(y[te], model.predict(X[te]), labels=classes,
                                        zero_division=0))
            print("Classes na matriz:", classes)
            print(confusion_matrix(y[te], model.predict(X[te]), labels=classes))
            print("ATENÇÃO: não prova que as classes correspondam a níveis de acetona.")
        else:
            print("AVISO: não foi possível separar todas as classes nos conjuntos de treino e teste.")
    else:
        print("\nATENÇÃO: menos de 3 arquivos independentes por classe.")
        print("Treinamento demonstrativo, sem avaliação confiável de desempenho.")
    model.fit(X, y)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"modelo": model, "campos": COLS, "descricao": "Classificação exploratória multiclasse dos padrões do hálito; NÃO mede acetona", "classes": classes}, output)
    print(f"\nModelo salvo: {output}")
    print("As probabilidades do classificador NÃO representam acetona em ppm.")


def predict(file, model_path):
    import joblib
    obj = joblib.load(model_path)  # Carregar somente modelos gerados por você, de fonte confiável.
    cycles, _ = features_from_file(file)
    X = np.asarray([x for _, x in cycles], dtype=float)
    probs = obj["modelo"].predict_proba(X)
    classes = list(obj["modelo"].classes_)
    medias = np.mean(probs, axis=0)
    print(f"Arquivo: {file.name}; ciclos analisados: {len(X)}")
    print("Semelhança estatística às classes de treinamento (média das probabilidades):")
    for cls, val in sorted(zip(classes, medias), key=lambda par: par[1], reverse=True):
        print(f"  {cls}: {val:.1%}")
    print("Classe mais provável:", classes[int(np.argmax(medias))])
    print("AVISO: classes são rótulos experimentais; NÃO representam ppm ou cetose diagnosticada.")


def main():
    ap = argparse.ArgumentParser(description="Treino experimental BME688: múltiplas condições de hálito; sem ppm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preparar"); p.add_argument("--pasta", type=Path, required=True)
    p = sub.add_parser("treinar"); p.add_argument("--pasta", type=Path, required=True); p.add_argument("--modelo", type=Path, default=Path("modelo_bme688.joblib"))
    p = sub.add_parser("prever"); p.add_argument("--arquivo", type=Path, required=True); p.add_argument("--modelo", type=Path, default=Path("modelo_bme688.joblib"))
    args = ap.parse_args()
    if args.cmd in ("preparar", "treinar"):
        if not args.pasta.is_dir():
            ap.error(f"Pasta inexistente: {args.pasta}")
    if args.cmd == "preparar": prepare(args.pasta)
    elif args.cmd == "treinar": train(args.pasta, args.modelo)
    else: predict(args.arquivo, args.modelo)

if __name__ == "__main__":
    main()
