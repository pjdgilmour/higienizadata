#!/usr/bin/env python3
import argparse
import csv
import getpass
import os
import subprocess
import sys
from collections import defaultdict


ACS_CBO = "515105"


LOTACAO_SQL = """
SELECT DISTINCT
    p.nu_cns::text AS cns,
    COALESCE(
        NULLIF(p.no_civil_profissional, ''),
        NULLIF(p.no_social_profissional, ''),
        NULLIF(p.no_profissional_filtro, '')
    ) AS nome,
    c.co_cbo_2002::text AS cbo,
    c.no_cbo AS ocupacao,
    us.nu_cnes::text AS cnes,
    us.no_unidade_saude AS unidade,
    e.nu_ine::text AS ine,
    e.no_equipe AS equipe,
    CASE WHEN l.dt_desativacao_lotacao IS NULL THEN 'sim' ELSE 'nao' END AS lotacao_ativa,
    NULL::bigint AS qtd_registros_dw,
    'lotacao' AS origem
FROM tb_lotacao l
JOIN tb_prof p
    ON p.co_seq_prof = l.co_prof
JOIN tb_cbo c
    ON c.co_cbo = l.co_cbo
LEFT JOIN tb_unidade_saude us
    ON us.co_seq_unidade_saude = l.co_unidade_saude
LEFT JOIN tb_equipe e
    ON e.co_seq_equipe = l.co_equipe
WHERE c.co_cbo_2002 = '515105'
{active_filter}
"""


DW_SQL = """
WITH producao AS (
    SELECT
        'visita_domiciliar' AS origem_dw,
        co_dim_profissional,
        co_dim_cbo,
        co_dim_unidade_saude,
        co_dim_equipe
    FROM tb_fat_visita_domiciliar

    UNION ALL

    SELECT
        'cad_individual' AS origem_dw,
        co_dim_profissional,
        co_dim_cbo,
        co_dim_unidade_saude,
        co_dim_equipe
    FROM tb_fat_cad_individual

    UNION ALL

    SELECT
        'cad_domiciliar' AS origem_dw,
        co_dim_profissional,
        co_dim_cbo,
        co_dim_unidade_saude,
        co_dim_equipe
    FROM tb_fat_cad_domiciliar

    UNION ALL

    SELECT
        'atendimento_individual' AS origem_dw,
        co_dim_profissional_1,
        co_dim_cbo_1,
        co_dim_unidade_saude_1,
        co_dim_equipe_1
    FROM tb_fat_atendimento_individual
),
acs AS (
    SELECT
        co_dim_profissional,
        co_dim_cbo,
        co_dim_unidade_saude,
        co_dim_equipe,
        COUNT(*) AS qtd_registros_dw
    FROM producao
    GROUP BY
        co_dim_profissional,
        co_dim_cbo,
        co_dim_unidade_saude,
        co_dim_equipe
)
SELECT
    p.nu_cns::text AS cns,
    p.no_profissional AS nome,
    c.nu_cbo::text AS cbo,
    c.no_cbo AS ocupacao,
    us.nu_cnes::text AS cnes,
    us.no_unidade_saude AS unidade,
    e.nu_ine::text AS ine,
    e.no_equipe AS equipe,
    NULL::text AS lotacao_ativa,
    acs.qtd_registros_dw,
    'dw' AS origem
FROM acs
JOIN tb_dim_profissional p
    ON p.co_seq_dim_profissional = acs.co_dim_profissional
JOIN tb_dim_cbo c
    ON c.co_seq_dim_cbo = acs.co_dim_cbo
LEFT JOIN tb_dim_unidade_saude us
    ON us.co_seq_dim_unidade_saude = acs.co_dim_unidade_saude
LEFT JOIN tb_dim_equipe e
    ON e.co_seq_dim_equipe = acs.co_dim_equipe
WHERE c.nu_cbo = '515105'
"""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Lista profissionais ACS no e-SUS APS usando lotacao operacional e/ou DW."
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "localhost"))
    parser.add_argument("--port", default=os.getenv("PGPORT", "5432"))
    parser.add_argument("--database", "-d", default=os.getenv("PGDATABASE", "esus"))
    parser.add_argument("--user", "-U", default=os.getenv("PGUSER", "esus_leitura"))
    parser.add_argument(
        "--source",
        choices=["all", "lotacao", "dw"],
        default="all",
        help="Fonte dos dados: lotacao, dw ou all.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Inclui lotacoes desativadas na fonte operacional.",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Imprime CSV em vez de tabela simples.",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Nao consolida por profissional; mostra uma linha por unidade/equipe.",
    )
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


def row_key(row):
    return (
        row.get("cns") or "",
        (row.get("nome") or "").upper(),
        row.get("cbo") or ACS_CBO,
        row.get("cnes") or "",
        row.get("ine") or "",
    )


def merge_rows(rows):
    merged = {}
    sources = defaultdict(set)

    for row in rows:
        key = row_key(row)
        current = merged.setdefault(key, dict(row))
        sources[key].add(row["origem"])

        if row.get("qtd_registros_dw"):
            current["qtd_registros_dw"] = str(
                int(current.get("qtd_registros_dw") or 0)
                + int(row["qtd_registros_dw"])
            )
        if row.get("lotacao_ativa") == "sim":
            current["lotacao_ativa"] = "sim"
        elif "lotacao_ativa" not in current:
            current["lotacao_ativa"] = row.get("lotacao_ativa") or ""

        for field in ("cns", "nome", "cbo", "ocupacao", "cnes", "unidade", "ine", "equipe"):
            if not current.get(field) and row.get(field):
                current[field] = row[field]

    for key, row in merged.items():
        row["origem"] = "+".join(sorted(sources[key]))

    return sorted(
        merged.values(),
        key=lambda r: (
            (r.get("nome") or "").upper(),
            r.get("unidade") or "",
            r.get("equipe") or "",
        ),
    )


def professional_key(row):
    cns = row.get("cns") or ""
    if cns:
        return ("cns", cns)
    return ("nome", (row.get("nome") or "").upper(), row.get("cbo") or ACS_CBO)


def compact_by_professional(rows):
    compact = {}
    units = defaultdict(set)
    teams = defaultdict(set)
    cnes_values = defaultdict(set)
    ine_values = defaultdict(set)
    sources = defaultdict(set)

    for row in rows:
        key = professional_key(row)
        current = compact.setdefault(key, dict(row))
        sources[key].update((row.get("origem") or "").split("+"))

        if row.get("unidade"):
            units[key].add(row["unidade"])
        if row.get("equipe"):
            teams[key].add(row["equipe"])
        if row.get("cnes"):
            cnes_values[key].add(row["cnes"])
        if row.get("ine"):
            ine_values[key].add(row["ine"])

        if row.get("lotacao_ativa") == "sim":
            current["lotacao_ativa"] = "sim"
        elif "lotacao_ativa" not in current:
            current["lotacao_ativa"] = row.get("lotacao_ativa") or ""

        current["qtd_registros_dw"] = str(
            int(current.get("qtd_registros_dw") or 0)
            + int(row.get("qtd_registros_dw") or 0)
        )

        for field in ("cns", "nome", "cbo", "ocupacao"):
            if not current.get(field) and row.get(field):
                current[field] = row[field]

    for key, row in compact.items():
        row["unidade"] = "; ".join(sorted(units[key]))
        row["equipe"] = "; ".join(sorted(teams[key]))
        row["cnes"] = "; ".join(sorted(cnes_values[key]))
        row["ine"] = "; ".join(sorted(ine_values[key]))
        row["origem"] = "+".join(sorted(source for source in sources[key] if source))

    return sorted(compact.values(), key=lambda r: (r.get("nome") or "").upper())


def print_table(rows):
    fields = [
        "nome",
        "cns",
        "cbo",
        "unidade",
        "equipe",
        "cnes",
        "ine",
        "lotacao_ativa",
        "qtd_registros_dw",
        "origem",
    ]
    widths = {
        field: min(
            max(len(field), *(len(str(row.get(field) or "")) for row in rows)),
            42,
        )
        for field in fields
    }

    def clip(value, width):
        value = str(value or "")
        return value if len(value) <= width else value[: width - 1] + "…"

    print(" | ".join(field.ljust(widths[field]) for field in fields))
    print("-+-".join("-" * widths[field] for field in fields))
    for row in rows:
        print(" | ".join(clip(row.get(field), widths[field]).ljust(widths[field]) for field in fields))


def print_csv(rows):
    fields = [
        "nome",
        "cns",
        "cbo",
        "ocupacao",
        "unidade",
        "equipe",
        "cnes",
        "ine",
        "lotacao_ativa",
        "qtd_registros_dw",
        "origem",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)


def main():
    args = parse_args()
    queries = []
    active_filter = "" if args.include_inactive else "AND l.dt_desativacao_lotacao IS NULL"

    if args.source in ("all", "lotacao"):
        queries.append(LOTACAO_SQL.format(active_filter=active_filter))
    if args.source in ("all", "dw"):
        queries.append(DW_SQL)

    rows = []
    for sql in queries:
        rows.extend(run_psql(args, sql))
    rows = merge_rows(rows)
    if not args.details:
        rows = compact_by_professional(rows)

    if args.csv:
        print_csv(rows)
    else:
        print(f"ACS encontrados: {len(rows)}")
        print_table(rows)


if __name__ == "__main__":
    main()
