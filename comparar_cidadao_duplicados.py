#!/usr/bin/env python3
import argparse
import csv
import getpass
import os
import subprocess
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher


DEFAULT_INPUT = "cidadaoDuplicados.csv"
DEFAULT_OUTPUT = "comparacao_cidadaoDuplicados.txt"


BASE_SQL = """
SELECT
    co_seq_cds_cad_individual::text AS id_cadastro,
    no_cidadao AS nome,
    no_cidadao_filtro AS nome_filtro,
    dt_nascimento::text AS nascimento_full,
    dt_nascimento::date::text AS nascimento,
    no_mae_cidadao AS nome_mae,
    nu_cpf_cidadao AS cpf,
    nu_cns_cidadao AS cns,
    st_versao_atual::text AS versao_atual,
    st_ficha_inativa::text AS ficha_inativa,
    st_recusa_cad::text AS recusa_cadastro
FROM tb_cds_cad_individual
WHERE COALESCE(st_versao_atual, 1) = 1
  AND COALESCE(st_ficha_inativa, 0) = 0
  AND COALESCE(st_recusa_cad, 0) = 0;
"""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compara cidadaoDuplicados.csv com duplicidades encontradas no banco."
    )
    parser.add_argument("--input", "-i", default=DEFAULT_INPUT)
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT)
    parser.add_argument("--host", default=os.getenv("PGHOST", "localhost"))
    parser.add_argument("--port", default=os.getenv("PGPORT", "5432"))
    parser.add_argument("--database", "-d", default=os.getenv("PGDATABASE", "esus"))
    parser.add_argument("--user", "-U", default=os.getenv("PGUSER", "esus_leitura"))
    return parser.parse_args()


def run_psql(args, sql):
    env = os.environ.copy()
    if "PGPASSWORD" not in env:
        env["PGPASSWORD"] = getpass.getpass(f"Senha do usuario {args.user}: ")

    cmd = [
        "psql",
        "-h",
        args.host,
        "-p",
        str(args.port),
        "-U",
        args.user,
        "-d",
        args.database,
        "--csv",
        "-q",
        "-c",
        sql,
    ]
    proc = subprocess.run(cmd, env=env, text=True, capture_output=True)
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        sys.exit(proc.returncode)
    return list(csv.DictReader(proc.stdout.splitlines()))


def normalize_text(value):
    value = " ".join((value or "").strip().upper().split())
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def strict_text(value):
    return " ".join((value or "").strip().upper().split())


def normalize_date(value):
    value = (value or "").strip()
    if "T" in value:
        return value.split("T", 1)[0]
    if " " in value:
        return value.split(" ", 1)[0]
    return value


def valid_digits(value, length):
    value = (value or "").strip()
    digits = "".join(ch for ch in value if ch.isdigit())
    if value and value == digits and len(digits) == length:
        return digits
    return ""


def load_system_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as csvfile:
        rows = list(csv.DictReader(csvfile))

    parsed = []
    for row in rows:
        ids = [item for item in (row.get("codigoIds") or "").split(";") if item]
        parsed.append(
            {
                "id": row.get("id") or "",
                "nome": row.get("nome") or "",
                "nome_norm": normalize_text(row.get("nome")),
                "nascimento": normalize_date(row.get("nascimento")),
                "cpf": valid_digits(row.get("cpf"), 11),
                "cns": valid_digits(row.get("cns"), 15),
                "telefone": row.get("telefone") or "",
                "codigo_ids": ids,
                "nao_duplicado": row.get("naoDuplicado") or "",
            }
        )
    return parsed


def group_db_duplicates(base_rows):
    by_cpf = defaultdict(list)
    by_cns = defaultdict(list)
    by_identity = defaultdict(list)

    for row in base_rows:
        row["nome_strict"] = strict_text(row.get("nome_filtro"))
        row["mae_strict"] = strict_text(row.get("nome_mae"))
        row["nome_norm"] = normalize_text(row.get("nome_filtro") or row.get("nome"))
        row["mae_norm"] = normalize_text(row.get("nome_mae"))
        row["nascimento"] = normalize_date(row.get("nascimento"))
        row["cpf_digits"] = valid_digits(row.get("cpf"), 11)
        row["cns_digits"] = valid_digits(row.get("cns"), 15)

        if row["cpf_digits"]:
            by_cpf[row["cpf_digits"]].append(row)
        if row["cns_digits"]:
            by_cns[row["cns_digits"]].append(row)
        if row["nome_strict"] and row.get("nascimento_full"):
            by_identity[
                (row["nome_strict"], row["nascimento_full"], row["mae_strict"])
            ].append(row)

    groups = []
    for key, rows in by_cpf.items():
        if len(rows) > 1:
            groups.append(("CPF", key, rows))
    for key, rows in by_cns.items():
        if len(rows) > 1:
            groups.append(("CNS", key, rows))
    for key, rows in by_identity.items():
        if len(rows) > 1:
            groups.append(("NOME_NASC_MAE", key, rows))
    return groups


def build_indexes(base_rows, db_groups):
    base_by_name_date = defaultdict(list)
    groups_by_name_date = defaultdict(list)
    groups_by_cpf = defaultdict(list)
    groups_by_cns = defaultdict(list)

    for row in base_rows:
        base_by_name_date[(row["nome_norm"], row["nascimento"])].append(row)

    for criterion, key, rows in db_groups:
        for row in rows:
            groups_by_name_date[(row["nome_norm"], row["nascimento"])].append((criterion, key, rows))
        if criterion == "CPF":
            groups_by_cpf[key].append((criterion, key, rows))
        if criterion == "CNS":
            groups_by_cns[key].append((criterion, key, rows))

    return base_by_name_date, groups_by_name_date, groups_by_cpf, groups_by_cns


def best_similar(row, base_rows):
    same_date = [item for item in base_rows if item["nascimento"] == row["nascimento"]]
    best = None
    best_score = 0.0
    for item in same_date:
        score = SequenceMatcher(None, row["nome_norm"], item["nome_norm"]).ratio()
        if score > best_score:
            best = item
            best_score = score
    return best, best_score


def write_report(args, system_rows, base_rows, db_groups):
    base_by_name_date, groups_by_name_date, groups_by_cpf, groups_by_cns = build_indexes(
        base_rows, db_groups
    )
    system_exact_in_db_group = []
    system_exact_in_base_only = []
    system_by_doc_in_db_group = []
    system_not_found_exact = []

    for row in system_rows:
        exact_key = (row["nome_norm"], row["nascimento"])
        matched_group = bool(groups_by_name_date.get(exact_key))
        matched_doc = bool(
            (row["cpf"] and groups_by_cpf.get(row["cpf"]))
            or (row["cns"] and groups_by_cns.get(row["cns"]))
        )
        matched_base = bool(base_by_name_date.get(exact_key))

        if matched_group:
            system_exact_in_db_group.append(row)
        elif matched_doc:
            system_by_doc_in_db_group.append(row)
        elif matched_base:
            system_exact_in_base_only.append(row)
        else:
            system_not_found_exact.append(row)

    system_name_dates = {(row["nome_norm"], row["nascimento"]) for row in system_rows}
    db_groups_in_system = []
    db_groups_not_in_system = []
    seen_group_keys = set()
    for criterion, key, rows in db_groups:
        group_id = (criterion, str(key))
        if group_id in seen_group_keys:
            continue
        seen_group_keys.add(group_id)
        has_system = any((row["nome_norm"], row["nascimento"]) in system_name_dates for row in rows)
        if has_system:
            db_groups_in_system.append((criterion, key, rows))
        else:
            db_groups_not_in_system.append((criterion, key, rows))

    with open(args.output, "w", encoding="utf-8") as report:
        report.write("COMPARACAO - cidadaoDuplicados.csv x BANCO RESTAURADO\n")
        report.write("=" * 72 + "\n")
        report.write(f"Gerado em               : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        report.write(f"CSV                     : {args.input}\n")
        report.write("Banco                   : tb_cds_cad_individual\n")
        report.write("Universo do banco       : versao atual + ativa + sem recusa\n\n")

        report.write("RESUMO\n")
        report.write("-" * 72 + "\n")
        report.write(f"Linhas no CSV do sistema                  : {len(system_rows)}\n")
        report.write(
            f"IDs em codigoIds no CSV                   : {sum(len(row['codigo_ids']) for row in system_rows)}\n"
        )
        report.write(
            f"IDs unicos em codigoIds no CSV            : {len({item for row in system_rows for item in row['codigo_ids']})}\n"
        )
        report.write(f"Registros atuais/ativos no banco          : {len(base_rows)}\n")
        report.write(f"Grupos estritos no banco                  : {len(db_groups)}\n")
        report.write(f"CSV bate com grupo estrito por nome+data  : {len(system_exact_in_db_group)}\n")
        report.write(f"CSV bate com grupo estrito por CPF/CNS    : {len(system_by_doc_in_db_group)}\n")
        report.write(f"CSV existe no banco, mas nao no grupo     : {len(system_exact_in_base_only)}\n")
        report.write(f"CSV sem match exato nome+data no banco    : {len(system_not_found_exact)}\n")
        report.write(f"Grupos do banco presentes no CSV          : {len(db_groups_in_system)}\n")
        report.write(f"Grupos do banco ausentes no CSV           : {len(db_groups_not_in_system)}\n\n")

        report.write("LEITURA\n")
        report.write("-" * 72 + "\n")
        report.write(
            "O CSV do sistema aparenta usar um criterio diferente do relatorio estrito.\n"
        )
        report.write(
            "Ele agrupa casos com variacao de nome/sobrenome e usa IDs que nao batem\n"
        )
        report.write(
            "diretamente com co_seq_cds_cad_individual. Por isso a comparacao principal\n"
        )
        report.write("foi feita por nome normalizado, data de nascimento, CPF e CNS.\n\n")

        report.write("AMOSTRA - CSV QUE EXISTE NO BANCO MAS NAO CAIU NO GRUPO ESTRITO\n")
        report.write("-" * 72 + "\n")
        for row in system_exact_in_base_only[:30]:
            current_count = len(base_by_name_date[(row["nome_norm"], row["nascimento"])])
            report.write(
                f"{row['nome']} | nasc {row['nascimento']} | linhas atuais no banco: {current_count} | ids CSV: {';'.join(row['codigo_ids'])}\n"
            )
        if not system_exact_in_base_only:
            report.write("Sem registros.\n")
        report.write("\n")

        report.write("AMOSTRA - CSV SEM MATCH EXATO NO BANCO, COM MELHOR APROXIMACAO\n")
        report.write("-" * 72 + "\n")
        for row in system_not_found_exact[:30]:
            best, score = best_similar(row, base_rows)
            if best:
                report.write(
                    f"{row['nome']} | nasc {row['nascimento']} -> {best.get('nome')} | score {score:.2f} | id banco {best.get('id_cadastro')}\n"
                )
            else:
                report.write(f"{row['nome']} | nasc {row['nascimento']} -> sem candidato\n")
        if not system_not_found_exact:
            report.write("Sem registros.\n")
        report.write("\n")

        report.write("AMOSTRA - GRUPOS ESTRITOS DO BANCO AUSENTES NO CSV DO SISTEMA\n")
        report.write("-" * 72 + "\n")
        for criterion, key, rows in db_groups_not_in_system[:40]:
            first = rows[0]
            report.write(
                f"{criterion} | {first.get('nome')} | nasc {first.get('nascimento')} | mae {first.get('nome_mae') or '-'} | registros {len(rows)}\n"
            )
        if not db_groups_not_in_system:
            report.write("Sem registros.\n")


def main():
    args = parse_args()
    system_rows = load_system_csv(args.input)
    base_rows = run_psql(args, BASE_SQL)
    db_groups = group_db_duplicates(base_rows)
    write_report(args, system_rows, base_rows, db_groups)
    print(f"Relatorio gerado: {args.output}")
    print(f"Linhas no CSV: {len(system_rows)}")
    print(f"Grupos estritos no banco: {len(db_groups)}")


if __name__ == "__main__":
    main()
