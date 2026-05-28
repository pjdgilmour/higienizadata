#!/usr/bin/env python3
import argparse
import csv
import getpass
import os
import subprocess
import sys


DEFAULT_OUTPUT = "nomes_cadastros_duplicados.txt"


SQL = """
WITH base AS (
    SELECT
        ci.no_cidadao,
        ci.no_cidadao_filtro,
        ci.dt_nascimento,
        ci.no_mae_cidadao,
        NULLIF(regexp_replace(COALESCE(ci.nu_cpf_cidadao, ''), '[^0-9]', '', 'g'), '') AS cpf_key,
        NULLIF(regexp_replace(COALESCE(ci.nu_cns_cidadao, ''), '[^0-9]', '', 'g'), '') AS cns_key,
        NULLIF(upper(trim(COALESCE(ci.no_cidadao_filtro, ci.no_cidadao, ''))), '') AS nome_key,
        NULLIF(upper(trim(COALESCE(ci.no_mae_cidadao, ''))), '') AS mae_key
    FROM tb_cds_cad_individual ci
    WHERE 1 = 1
        {current_filter}
        {inactive_filter}
        {refusal_filter}
),
duplicate_keys AS (
    SELECT 'CPF' AS criterio, cpf_key AS chave
    FROM base
    WHERE cpf_key IS NOT NULL
    GROUP BY cpf_key
    HAVING COUNT(*) > 1

    UNION ALL

    SELECT 'CNS' AS criterio, cns_key AS chave
    FROM base
    WHERE cns_key IS NOT NULL
    GROUP BY cns_key
    HAVING COUNT(*) > 1

    UNION ALL

    SELECT
        'NOME_NASC_MAE' AS criterio,
        nome_key || ' | ' || COALESCE(dt_nascimento::text, '') || ' | ' || COALESCE(mae_key, '') AS chave
    FROM base
    WHERE nome_key IS NOT NULL
        AND dt_nascimento IS NOT NULL
    GROUP BY nome_key, dt_nascimento, mae_key
    HAVING COUNT(*) > 1
),
records AS (
    SELECT b.no_cidadao, b.nome_key
    FROM duplicate_keys dk
    JOIN base b
        ON dk.criterio = 'CPF'
        AND b.cpf_key = dk.chave

    UNION ALL

    SELECT b.no_cidadao, b.nome_key
    FROM duplicate_keys dk
    JOIN base b
        ON dk.criterio = 'CNS'
        AND b.cns_key = dk.chave

    UNION ALL

    SELECT b.no_cidadao, b.nome_key
    FROM duplicate_keys dk
    JOIN base b
        ON dk.criterio = 'NOME_NASC_MAE'
        AND b.nome_key || ' | ' || COALESCE(b.dt_nascimento::text, '') || ' | ' || COALESCE(b.mae_key, '') = dk.chave
)
SELECT
    nome_key,
    MIN(NULLIF(trim(no_cidadao), '')) AS nome
FROM records
WHERE nome_key IS NOT NULL
GROUP BY nome_key
ORDER BY nome_key;
"""


LOWER_WORDS = {"da", "das", "de", "do", "dos", "e"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Gera um TXT com nomes unicos de cadastros individuais duplicados."
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "localhost"))
    parser.add_argument("--port", default=os.getenv("PGPORT", "5432"))
    parser.add_argument("--database", "-d", default=os.getenv("PGDATABASE", "esus"))
    parser.add_argument("--user", "-U", default=os.getenv("PGUSER", "esus_leitura"))
    parser.add_argument(
        "--output",
        "-o",
        default=DEFAULT_OUTPUT,
        help=f"Arquivo TXT de saida. Padrao: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--keep-case",
        action="store_true",
        help="Mantem o nome exatamente como veio do banco.",
    )
    parser.add_argument(
        "--include-old-versions",
        action="store_true",
        help="Inclui fichas que nao sao a versao atual.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Inclui fichas inativas.",
    )
    parser.add_argument(
        "--include-refused",
        action="store_true",
        help="Inclui fichas com recusa de cadastro.",
    )
    return parser.parse_args()


def build_sql(args):
    return SQL.format(
        current_filter=""
        if args.include_old_versions
        else "AND COALESCE(ci.st_versao_atual, 1) = 1",
        inactive_filter=""
        if args.include_inactive
        else "AND COALESCE(ci.st_ficha_inativa, 0) = 0",
        refusal_filter=""
        if args.include_refused
        else "AND COALESCE(ci.st_recusa_cad, 0) = 0",
    )


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


def pretty_name(name):
    parts = " ".join((name or "").split()).lower().split(" ")
    pretty = []
    for index, part in enumerate(parts):
        if index > 0 and part in LOWER_WORDS:
            pretty.append(part)
        else:
            pretty.append(part[:1].upper() + part[1:])
    return " ".join(pretty)


def main():
    args = parse_args()
    rows = run_psql(args, build_sql(args))
    names = []
    seen = set()

    for row in rows:
        name = (row.get("nome") or row.get("nome_key") or "").strip()
        if not name:
            continue
        output_name = name if args.keep_case else pretty_name(name)
        key = output_name.upper()
        if key in seen:
            continue
        seen.add(key)
        names.append(output_name)

    with open(args.output, "w", encoding="utf-8") as output:
        output.write("\n".join(names))
        if names:
            output.write("\n")

    print(f"Arquivo gerado: {args.output}")
    print(f"Nomes unicos: {len(names)}")


if __name__ == "__main__":
    main()
