#!/usr/bin/env python3
import argparse
import csv
import getpass
import os
import subprocess
import sys
from datetime import datetime


DEFAULT_OUTPUT = "relatorio_origem_gordura_pec.txt"
DEFAULT_SISTEMA_TERCEIRO_TOTAL = 26299
DEFAULT_REFERENCIA_ESPERADA = 25000
PERIODO_PICO_INICIO = "2025-11-01"
PERIODO_PICO_FIM = "2026-02-01"


BASE_FILTER = """
WHERE COALESCE(ci.st_versao_atual, 1) = 1
  AND COALESCE(ci.st_ficha_inativa, 0) = 0
  AND COALESCE(ci.st_recusa_cad, 0) = 0
"""


PEAK_FILTER = f"""
{BASE_FILTER}
  AND ci.dt_cad_individual >= DATE '{PERIODO_PICO_INICIO}'
  AND ci.dt_cad_individual < DATE '{PERIODO_PICO_FIM}'
"""


QUERIES = {
    "resumo": f"""
        WITH base AS (
            SELECT
                ci.*,
                NULLIF(regexp_replace(COALESCE(ci.nu_cpf_cidadao, ''), '[^0-9]', '', 'g'), '') AS cpf_digits,
                NULLIF(regexp_replace(COALESCE(ci.nu_cns_cidadao, ''), '[^0-9]', '', 'g'), '') AS cns_digits
            FROM tb_cds_cad_individual ci
            {BASE_FILTER}
        ),
        pico AS (
            SELECT *
            FROM base
            WHERE dt_cad_individual >= DATE '{PERIODO_PICO_INICIO}'
              AND dt_cad_individual < DATE '{PERIODO_PICO_FIM}'
        )
        SELECT 'Cadastros atuais/ativos/sem recusa no PEC' AS indicador, COUNT(*)::text AS valor
        FROM base
        UNION ALL
        SELECT 'Cadastros no periodo critico 2025-11 a 2026-01', COUNT(*)::text
        FROM pico
        UNION ALL
        SELECT 'Cadastros fora do periodo critico', (SELECT COUNT(*) FROM base) - (SELECT COUNT(*) FROM pico)::bigint || ''
        UNION ALL
        SELECT 'Sem CPF no periodo critico', COUNT(*)::text
        FROM pico
        WHERE cpf_digits IS NULL
        UNION ALL
        SELECT 'Sem CNS no periodo critico', COUNT(*)::text
        FROM pico
        WHERE cns_digits IS NULL
        UNION ALL
        SELECT 'Sem CPF e sem CNS no periodo critico', COUNT(*)::text
        FROM pico
        WHERE cpf_digits IS NULL AND cns_digits IS NULL
        UNION ALL
        SELECT 'Fora de area no periodo critico', COUNT(*)::text
        FROM pico
        WHERE COALESCE(st_fora_area, 0) = 1
        UNION ALL
        SELECT 'Com obito no periodo critico', COUNT(*)::text
        FROM pico
        WHERE dt_obito IS NOT NULL;
    """,
    "periodos": f"""
        SELECT periodo, COUNT(*)::text AS qtd
        FROM (
            SELECT
                CASE
                    WHEN ci.dt_cad_individual < DATE '{PERIODO_PICO_INICIO}' THEN 'Antes de 2025-11'
                    WHEN ci.dt_cad_individual >= DATE '{PERIODO_PICO_INICIO}'
                     AND ci.dt_cad_individual < DATE '{PERIODO_PICO_FIM}' THEN 'Periodo critico: 2025-11 a 2026-01'
                    WHEN ci.dt_cad_individual >= DATE '{PERIODO_PICO_FIM}' THEN 'Depois de 2026-01'
                    ELSE 'Sem data'
                END AS periodo
            FROM tb_cds_cad_individual ci
            {BASE_FILTER}
        ) x
        GROUP BY periodo
        ORDER BY
            CASE periodo
                WHEN 'Antes de 2025-11' THEN 1
                WHEN 'Periodo critico: 2025-11 a 2026-01' THEN 2
                WHEN 'Depois de 2026-01' THEN 3
                ELSE 4
            END;
    """,
    "meses": f"""
        SELECT
            COALESCE(date_trunc('month', ci.dt_cad_individual)::date::text, 'SEM DATA') AS mes,
            COUNT(*)::text AS qtd,
            COUNT(*) FILTER (WHERE NULLIF(regexp_replace(COALESCE(ci.nu_cpf_cidadao, ''), '[^0-9]', '', 'g'), '') IS NULL)::text AS sem_cpf,
            COUNT(*) FILTER (WHERE NULLIF(regexp_replace(COALESCE(ci.nu_cns_cidadao, ''), '[^0-9]', '', 'g'), '') IS NULL)::text AS sem_cns,
            COUNT(*) FILTER (WHERE COALESCE(ci.st_fora_area, 0) = 1)::text AS fora_area,
            COUNT(*) FILTER (WHERE ci.dt_obito IS NOT NULL)::text AS com_obito
        FROM tb_cds_cad_individual ci
        {BASE_FILTER}
        GROUP BY 1
        ORDER BY COUNT(*) DESC
        LIMIT 24;
    """,
    "origem_pico": f"""
        SELECT
            COALESCE(ci.tp_cds_origem::text, '-') AS origem,
            COUNT(*)::text AS qtd,
            COUNT(*) FILTER (WHERE NULLIF(regexp_replace(COALESCE(ci.nu_cpf_cidadao, ''), '[^0-9]', '', 'g'), '') IS NULL)::text AS sem_cpf,
            COUNT(*) FILTER (WHERE NULLIF(regexp_replace(COALESCE(ci.nu_cns_cidadao, ''), '[^0-9]', '', 'g'), '') IS NULL)::text AS sem_cns
        FROM tb_cds_cad_individual ci
        {PEAK_FILTER}
        GROUP BY ci.tp_cds_origem
        ORDER BY COUNT(*) DESC;
    """,
    "microarea_pico": f"""
        SELECT
            COALESCE(NULLIF(ci.nu_micro_area, ''), 'SEM MICROAREA') AS micro_area,
            COUNT(*)::text AS qtd,
            COUNT(*) FILTER (WHERE COALESCE(ci.st_fora_area, 0) = 1)::text AS fora_area,
            COUNT(*) FILTER (WHERE ci.dt_obito IS NOT NULL)::text AS com_obito
        FROM tb_cds_cad_individual ci
        {PEAK_FILTER}
        GROUP BY 1
        ORDER BY COUNT(*) DESC
        LIMIT 40;
    """,
    "profissional_pico": f"""
        SELECT
            COALESCE(prof.nu_cns, '-') AS cns_profissional,
            COALESCE(prof.nu_ine, '-') AS ine,
            COALESCE(prof.nu_cbo_2002, '-') AS cbo,
            COUNT(*)::text AS qtd
        FROM tb_cds_cad_individual ci
        LEFT JOIN tb_cds_prof prof
            ON prof.co_seq_cds_prof = ci.co_cds_prof_cadastrante
        {PEAK_FILTER}
        GROUP BY prof.nu_cns, prof.nu_ine, prof.nu_cbo_2002
        ORDER BY COUNT(*) DESC
        LIMIT 40;
    """,
    "fora_area_obito": f"""
        SELECT
            categoria,
            COUNT(*)::text AS qtd
        FROM (
            SELECT
                CASE
                    WHEN COALESCE(ci.st_fora_area, 0) = 1 AND ci.dt_obito IS NOT NULL THEN 'Fora de area + obito'
                    WHEN COALESCE(ci.st_fora_area, 0) = 1 THEN 'Somente fora de area'
                    WHEN ci.dt_obito IS NOT NULL THEN 'Somente obito'
                    ELSE 'Nem fora de area nem obito'
                END AS categoria
            FROM tb_cds_cad_individual ci
            {BASE_FILTER}
        ) x
        GROUP BY categoria
        ORDER BY COUNT(*) DESC;
    """,
    "duplicidade_pico": f"""
        WITH base AS (
            SELECT
                ci.*,
                NULLIF(upper(trim(COALESCE(ci.no_cidadao_filtro, ''))), '') AS nome_key,
                NULLIF(upper(trim(COALESCE(ci.no_mae_cidadao, ''))), '') AS mae_key
            FROM tb_cds_cad_individual ci
            {BASE_FILTER}
        ),
        grupos AS (
            SELECT
                nome_key,
                dt_nascimento,
                mae_key,
                COUNT(*) AS qtd,
                COUNT(*) FILTER (
                    WHERE dt_cad_individual >= DATE '{PERIODO_PICO_INICIO}'
                      AND dt_cad_individual < DATE '{PERIODO_PICO_FIM}'
                ) AS qtd_no_pico
            FROM base
            WHERE nome_key IS NOT NULL
                AND dt_nascimento IS NOT NULL
            GROUP BY nome_key, dt_nascimento, mae_key
            HAVING COUNT(*) > 1
        )
        SELECT
            'Grupos duplicados totais' AS indicador,
            COUNT(*)::text AS valor
        FROM grupos
        UNION ALL
        SELECT
            'Grupos duplicados com ao menos um cadastro no periodo critico',
            COUNT(*)::text
        FROM grupos
        WHERE qtd_no_pico > 0
        UNION ALL
        SELECT
            'Registros envolvidos em grupos duplicados',
            COALESCE(SUM(qtd), 0)::text
        FROM grupos
        UNION ALL
        SELECT
            'Registros do periodo critico dentro de grupos duplicados',
            COALESCE(SUM(qtd_no_pico), 0)::text
        FROM grupos;
    """,
    "amostra_pico_sem_documento": f"""
        SELECT
            ci.no_cidadao AS nome,
            ci.dt_nascimento::date::text AS nascimento,
            ci.no_mae_cidadao AS mae,
            ci.dt_cad_individual::date::text AS dt_cadastro,
            COALESCE(ci.nu_micro_area, '-') AS micro_area,
            COALESCE(ci.tp_cds_origem::text, '-') AS origem,
            COALESCE(prof.nu_cns, '-') AS cns_profissional
        FROM tb_cds_cad_individual ci
        LEFT JOIN tb_cds_prof prof
            ON prof.co_seq_cds_prof = ci.co_cds_prof_cadastrante
        {PEAK_FILTER}
          AND NULLIF(regexp_replace(COALESCE(ci.nu_cpf_cidadao, ''), '[^0-9]', '', 'g'), '') IS NULL
          AND NULLIF(regexp_replace(COALESCE(ci.nu_cns_cidadao, ''), '[^0-9]', '', 'g'), '') IS NULL
        ORDER BY ci.dt_cad_individual DESC, ci.no_cidadao
        LIMIT 80;
    """,
}


SECTIONS = [
    ("resumo", "Resumo do PEC e do periodo critico"),
    ("periodos", "Antes, durante e depois dos picos"),
    ("meses", "Meses com maior volume"),
    ("origem_pico", "Origem dos cadastros no periodo critico"),
    ("microarea_pico", "Microareas no periodo critico"),
    ("profissional_pico", "Profissionais cadastrantes no periodo critico"),
    ("fora_area_obito", "Fora de area e obitos no universo principal"),
    ("duplicidade_pico", "Duplicidades estritas relacionadas ao periodo critico"),
    ("amostra_pico_sem_documento", "Amostra do periodo critico sem CPF e sem CNS"),
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Gera relatorio TXT sobre possivel origem da gordura cadastral no PEC."
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "localhost"))
    parser.add_argument("--port", default=os.getenv("PGPORT", "5432"))
    parser.add_argument("--database", "-d", default=os.getenv("PGDATABASE", "esus"))
    parser.add_argument("--user", "-U", default=os.getenv("PGUSER", "esus_leitura"))
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--sistema-terceiro-total",
        type=int,
        default=DEFAULT_SISTEMA_TERCEIRO_TOTAL,
        help="Total de cidadaos exibido pelo sistema terceiro.",
    )
    parser.add_argument(
        "--referencia-esperada",
        type=int,
        default=DEFAULT_REFERENCIA_ESPERADA,
        help="Numero esperado aproximado de cidadaos.",
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


def render_table(rows):
    if not rows:
        return "Sem registros.\n"
    fields = list(rows[0].keys())
    widths = {
        field: min(
            max(len(field), *(len(str(row.get(field) or "")) for row in rows)),
            56,
        )
        for field in fields
    }

    def clip(value, width):
        value = str(value or "")
        return value if len(value) <= width else value[: width - 1] + "…"

    output = []
    output.append(" | ".join(field.ljust(widths[field]) for field in fields))
    output.append("-+-".join("-" * widths[field] for field in fields))
    for row in rows:
        output.append(
            " | ".join(clip(row.get(field), widths[field]).ljust(widths[field]) for field in fields)
        )
    return "\n".join(output) + "\n"


def get_metric(rows, name):
    for row in rows:
        if row.get("indicador") == name:
            try:
                return int(row.get("valor") or 0)
            except ValueError:
                return 0
    return 0


def fmt_number(value):
    return f"{value:,}".replace(",", ".")


def write_report(args, data):
    pec_total = get_metric(data["resumo"], "Cadastros atuais/ativos/sem recusa no PEC")
    peak_total = get_metric(data["resumo"], "Cadastros no periodo critico 2025-11 a 2026-01")
    diff_third = pec_total - args.sistema_terceiro_total
    diff_expected = pec_total - args.referencia_esperada

    with open(args.output, "w", encoding="utf-8") as report:
        report.write("RELATORIO - ORIGEM PROVAVEL DA GORDURA CADASTRAL NO PEC\n")
        report.write("=" * 76 + "\n")
        report.write(f"Gerado em              : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        report.write(f"Banco                  : {args.database}@{args.host}:{args.port}\n")
        report.write("Universo PEC analisado : cadastro individual atual + ativo + sem recusa\n")
        report.write(f"Sistema terceiro       : {fmt_number(args.sistema_terceiro_total)} cidadaos\n")
        report.write(f"Referencia esperada    : {fmt_number(args.referencia_esperada)} cidadaos\n")
        report.write("\n")

        report.write("LEITURA EXECUTIVA\n")
        report.write("-" * 76 + "\n")
        report.write(
            f"O PEC tem {fmt_number(pec_total)} cadastros individuais no universo principal.\n"
        )
        report.write(
            f"Isto fica {fmt_number(diff_third)} acima do total informado no sistema terceiro.\n"
        )
        report.write(
            f"Tambem fica {fmt_number(diff_expected)} acima da referencia de {fmt_number(args.referencia_esperada)}.\n"
        )
        report.write(
            f"No periodo critico de importacao/migracao ({PERIODO_PICO_INICIO} a 2026-01-31),\n"
        )
        report.write(
            f"foram encontrados {fmt_number(peak_total)} cadastros atuais/ativos/sem recusa.\n"
        )
        report.write(
            "Esse volume e suficiente para explicar a maior parte da diferenca entre PEC e sistema terceiro.\n\n"
        )

        for key, title in SECTIONS:
            report.write(title.upper() + "\n")
            report.write("-" * 76 + "\n")
            report.write(render_table(data[key]))
            report.write("\n")


def main():
    args = parse_args()
    data = {key: run_psql(args, QUERIES[key]) for key, _ in SECTIONS}
    write_report(args, data)

    pec_total = get_metric(data["resumo"], "Cadastros atuais/ativos/sem recusa no PEC")
    peak_total = get_metric(data["resumo"], "Cadastros no periodo critico 2025-11 a 2026-01")
    print(f"Relatorio gerado: {args.output}")
    print(f"PEC universo principal: {pec_total}")
    print(f"Periodo critico: {peak_total}")
    print(f"Diferenca PEC x sistema terceiro: {pec_total - args.sistema_terceiro_total}")


if __name__ == "__main__":
    main()
