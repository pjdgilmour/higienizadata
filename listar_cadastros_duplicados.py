#!/usr/bin/env python3
import argparse
import csv
import getpass
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime


DEFAULT_OUTPUT = "cadastros_individuais_duplicados.txt"


DUPLICATES_SQL = """
WITH base AS (
    SELECT
        ci.co_seq_cds_cad_individual,
        ci.co_unico_ficha,
        ci.co_unico_ficha_origem,
        ci.co_unico_grupo,
        ci.no_cidadao,
        ci.no_social_cidadao,
        ci.no_cidadao_filtro,
        ci.dt_nascimento,
        ci.no_mae_cidadao,
        ci.no_pai_cidadao,
        ci.nu_cpf_cidadao,
        ci.nu_cns_cidadao,
        ci.nu_celular_cidadao,
        ci.dt_cad_individual,
        ci.nu_micro_area,
        ci.st_fora_area,
        ci.st_atualizacao,
        ci.st_versao_atual,
        ci.st_ficha_inativa,
        ci.st_recusa_cad,
        ci.st_gerado_automaticamente,
        ci.co_unidade_saude,
        ci.co_cbo,
        ci.co_cds_prof_cadastrante,
        us.nu_cnes,
        us.no_unidade_saude,
        cbo.co_cbo_2002,
        cbo.no_cbo,
        prof.nu_cns AS nu_cns_profissional,
        prof.nu_ine AS nu_ine_profissional,
        prof.nu_cbo_2002 AS nu_cbo_profissional,
        NULLIF(regexp_replace(COALESCE(ci.nu_cpf_cidadao, ''), '[^0-9]', '', 'g'), '') AS cpf_key,
        NULLIF(regexp_replace(COALESCE(ci.nu_cns_cidadao, ''), '[^0-9]', '', 'g'), '') AS cns_key,
        NULLIF(upper(trim(COALESCE(ci.no_cidadao_filtro, ci.no_cidadao, ''))), '') AS nome_key,
        NULLIF(upper(trim(COALESCE(ci.no_mae_cidadao, ''))), '') AS mae_key
    FROM tb_cds_cad_individual ci
    LEFT JOIN tb_unidade_saude us
        ON us.co_seq_unidade_saude = ci.co_unidade_saude
    LEFT JOIN tb_cbo cbo
        ON cbo.co_cbo = ci.co_cbo
    LEFT JOIN tb_cds_prof prof
        ON prof.co_seq_cds_prof = ci.co_cds_prof_cadastrante
    WHERE 1 = 1
        {current_filter}
        {inactive_filter}
        {refusal_filter}
),
duplicate_keys AS (
    SELECT
        'CPF' AS criterio,
        cpf_key AS chave,
        COUNT(*) AS qtd
    FROM base
    WHERE cpf_key IS NOT NULL
    GROUP BY cpf_key
    HAVING COUNT(*) > 1

    UNION ALL

    SELECT
        'CNS' AS criterio,
        cns_key AS chave,
        COUNT(*) AS qtd
    FROM base
    WHERE cns_key IS NOT NULL
    GROUP BY cns_key
    HAVING COUNT(*) > 1

    UNION ALL

    SELECT
        'NOME_NASC_MAE' AS criterio,
        nome_key || ' | ' || COALESCE(dt_nascimento::text, '') || ' | ' || COALESCE(mae_key, '') AS chave,
        COUNT(*) AS qtd
    FROM base
    WHERE nome_key IS NOT NULL
        AND dt_nascimento IS NOT NULL
    GROUP BY nome_key, dt_nascimento, mae_key
    HAVING COUNT(*) > 1
),
records AS (
    SELECT dk.criterio, dk.chave, dk.qtd, b.*
    FROM duplicate_keys dk
    JOIN base b
        ON dk.criterio = 'CPF'
        AND b.cpf_key = dk.chave

    UNION ALL

    SELECT dk.criterio, dk.chave, dk.qtd, b.*
    FROM duplicate_keys dk
    JOIN base b
        ON dk.criterio = 'CNS'
        AND b.cns_key = dk.chave

    UNION ALL

    SELECT dk.criterio, dk.chave, dk.qtd, b.*
    FROM duplicate_keys dk
    JOIN base b
        ON dk.criterio = 'NOME_NASC_MAE'
        AND b.nome_key || ' | ' || COALESCE(b.dt_nascimento::text, '') || ' | ' || COALESCE(b.mae_key, '') = dk.chave
)
SELECT
    criterio,
    chave,
    qtd::text AS qtd_no_grupo,
    co_seq_cds_cad_individual::text AS id_cadastro,
    co_unico_ficha,
    co_unico_ficha_origem,
    co_unico_grupo,
    no_cidadao AS nome,
    no_social_cidadao AS nome_social,
    dt_nascimento::text AS dt_nascimento,
    no_mae_cidadao AS nome_mae,
    no_pai_cidadao AS nome_pai,
    nu_cpf_cidadao AS cpf,
    nu_cns_cidadao AS cns,
    nu_celular_cidadao AS celular,
    dt_cad_individual::text AS dt_cadastro,
    nu_micro_area,
    st_fora_area::text AS fora_area,
    st_atualizacao::text AS atualizacao,
    st_versao_atual::text AS versao_atual,
    st_ficha_inativa::text AS ficha_inativa,
    st_recusa_cad::text AS recusa_cadastro,
    st_gerado_automaticamente::text AS gerado_auto,
    nu_cnes,
    no_unidade_saude AS unidade_saude,
    co_cbo_2002 AS cbo_cadastrante,
    no_cbo AS ocupacao_cadastrante,
    nu_cns_profissional AS cns_profissional,
    nu_ine_profissional AS ine_profissional
FROM records
ORDER BY criterio, chave, dt_cad_individual DESC NULLS LAST, co_seq_cds_cad_individual;
"""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Gera relatorio TXT de cadastros individuais duplicados no e-SUS APS."
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
    parser.add_argument(
        "--max-groups",
        type=int,
        default=0,
        help="Limita a quantidade de grupos no TXT. 0 = sem limite.",
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


def build_sql(args):
    return DUPLICATES_SQL.format(
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


def group_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["criterio"], row["chave"])].append(row)
    return sorted(groups.items(), key=lambda item: (item[0][0], item[0][1]))


def fmt(value):
    value = "" if value is None else str(value)
    return value.strip() or "-"


def line(label, value, width=22):
    return f"{label:<{width}}: {fmt(value)}"


def group_title(criterio, chave):
    if criterio == "NOME_NASC_MAE":
        parts = chave.split(" | ")
        nome = parts[0] if len(parts) > 0 else chave
        nascimento = parts[1] if len(parts) > 1 else "-"
        mae = parts[2] if len(parts) > 2 else "-"
        return f"{criterio} - {nome} / nasc. {nascimento} / mae {mae}"
    return f"{criterio} - {chave}"


def write_report(args, rows):
    groups = group_rows(rows)
    if args.max_groups > 0:
        groups = groups[: args.max_groups]

    total_records = sum(len(group_rows_) for _, group_rows_ in groups)
    criteria_counter = Counter(key[0] for key, _ in groups)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(args.output, "w", encoding="utf-8") as report:
        report.write("RELATORIO DE CADASTROS INDIVIDUAIS DUPLICADOS\n")
        report.write("=" * 62 + "\n")
        report.write(f"Gerado em              : {now}\n")
        report.write(f"Banco                  : {args.database}@{args.host}:{args.port}\n")
        report.write("Tabela base            : tb_cds_cad_individual\n")
        report.write("Criterios              : CPF, CNS, NOME + NASCIMENTO + MAE\n")
        report.write(f"Somente versao atual   : {'nao' if args.include_old_versions else 'sim'}\n")
        report.write(f"Ignora fichas inativas : {'nao' if args.include_inactive else 'sim'}\n")
        report.write(f"Ignora recusas         : {'nao' if args.include_refused else 'sim'}\n")
        report.write(f"Grupos duplicados      : {len(groups)}\n")
        report.write(f"Registros envolvidos   : {total_records}\n")
        report.write("\n")

        report.write("RESUMO POR CRITERIO\n")
        report.write("-" * 62 + "\n")
        for criterio in ("CPF", "CNS", "NOME_NASC_MAE"):
            report.write(f"{criterio:<18} {criteria_counter.get(criterio, 0):>8} grupos\n")
        report.write("\n")

        for index, ((criterio, chave), group) in enumerate(groups, start=1):
            report.write(f"GRUPO {index:04d} | {len(group)} registros\n")
            report.write("-" * 62 + "\n")
            report.write(group_title(criterio, chave) + "\n\n")

            for row_index, row in enumerate(group, start=1):
                report.write(f"  Registro {row_index}\n")
                report.write("  " + line("id_cadastro", row.get("id_cadastro")) + "\n")
                report.write("  " + line("nome", row.get("nome")) + "\n")
                report.write("  " + line("nome_social", row.get("nome_social")) + "\n")
                report.write("  " + line("dt_nascimento", row.get("dt_nascimento")) + "\n")
                report.write("  " + line("mae", row.get("nome_mae")) + "\n")
                report.write("  " + line("pai", row.get("nome_pai")) + "\n")
                report.write("  " + line("cpf", row.get("cpf")) + "\n")
                report.write("  " + line("cns", row.get("cns")) + "\n")
                report.write("  " + line("celular", row.get("celular")) + "\n")
                report.write("  " + line("dt_cadastro", row.get("dt_cadastro")) + "\n")
                report.write("  " + line("uuid_ficha", row.get("co_unico_ficha")) + "\n")
                report.write("  " + line("uuid_origem", row.get("co_unico_ficha_origem")) + "\n")
                report.write("  " + line("grupo", row.get("co_unico_grupo")) + "\n")
                report.write("  " + line("unidade", row.get("unidade_saude")) + "\n")
                report.write("  " + line("cnes", row.get("nu_cnes")) + "\n")
                report.write("  " + line("micro_area", row.get("nu_micro_area")) + "\n")
                report.write("  " + line("fora_area", row.get("fora_area")) + "\n")
                report.write("  " + line("versao_atual", row.get("versao_atual")) + "\n")
                report.write("  " + line("ficha_inativa", row.get("ficha_inativa")) + "\n")
                report.write("  " + line("recusa_cadastro", row.get("recusa_cadastro")) + "\n")
                report.write("  " + line("cns_profissional", row.get("cns_profissional")) + "\n")
                report.write("  " + line("ine_profissional", row.get("ine_profissional")) + "\n")
                report.write("  " + line("cbo_cadastrante", row.get("cbo_cadastrante")) + "\n")
                report.write("\n")

            report.write("\n")


def main():
    args = parse_args()
    rows = run_psql(args, build_sql(args))
    write_report(args, rows)

    groups = group_rows(rows)
    print(f"Relatorio gerado: {args.output}")
    print(f"Grupos duplicados: {len(groups)}")
    print(f"Registros envolvidos: {sum(len(group) for _, group in groups)}")


if __name__ == "__main__":
    main()
