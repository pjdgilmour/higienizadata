#!/usr/bin/env python3
import argparse
import csv
import getpass
import os
import subprocess
import sys
from datetime import datetime


DEFAULT_OUTPUT = "relatorio_auditoria_cadastros.txt"


BASE_WHERE = """
WHERE COALESCE(ci.st_versao_atual, 1) = 1
  AND COALESCE(ci.st_ficha_inativa, 0) = 0
  AND COALESCE(ci.st_recusa_cad, 0) = 0
"""


QUERIES = {
    "totais": f"""
        SELECT 'Total bruto em tb_cds_cad_individual' AS indicador, COUNT(*)::text AS valor
        FROM tb_cds_cad_individual ci
        UNION ALL
        SELECT 'Versoes atuais', COUNT(*)::text
        FROM tb_cds_cad_individual ci
        WHERE COALESCE(ci.st_versao_atual, 1) = 1
        UNION ALL
        SELECT 'Versoes atuais + ativas + sem recusa', COUNT(*)::text
        FROM tb_cds_cad_individual ci
        {BASE_WHERE}
        UNION ALL
        SELECT 'Diferenca ate meta de 25.000', (COUNT(*) - 25000)::text
        FROM tb_cds_cad_individual ci
        {BASE_WHERE}
    """,
    "flags": f"""
        WITH base AS (
            SELECT
                ci.*,
                NULLIF(regexp_replace(COALESCE(ci.nu_cpf_cidadao, ''), '[^0-9]', '', 'g'), '') AS cpf_key,
                NULLIF(regexp_replace(COALESCE(ci.nu_cns_cidadao, ''), '[^0-9]', '', 'g'), '') AS cns_key
            FROM tb_cds_cad_individual ci
            {BASE_WHERE}
        )
        SELECT 'Fora da area' AS indicador, COUNT(*)::text AS valor
        FROM base
        WHERE COALESCE(st_fora_area, 0) = 1
        UNION ALL
        SELECT 'Sem CPF', COUNT(*)::text
        FROM base
        WHERE cpf_key IS NULL
        UNION ALL
        SELECT 'Sem CNS', COUNT(*)::text
        FROM base
        WHERE cns_key IS NULL
        UNION ALL
        SELECT 'Sem CPF e sem CNS', COUNT(*)::text
        FROM base
        WHERE cpf_key IS NULL AND cns_key IS NULL
        UNION ALL
        SELECT 'Gerado automaticamente', COUNT(*)::text
        FROM base
        WHERE COALESCE(st_gerado_automaticamente, 0) = 1
        UNION ALL
        SELECT 'Com data de obito', COUNT(*)::text
        FROM base
        WHERE dt_obito IS NOT NULL
        UNION ALL
        SELECT 'Marcado fora da area ou obito', COUNT(*)::text
        FROM base
        WHERE COALESCE(st_fora_area, 0) = 1 OR dt_obito IS NOT NULL
    """,
    "origem": f"""
        SELECT
            COALESCE(tp_cds_origem::text, '-') AS origem,
            COUNT(*)::text AS qtd
        FROM tb_cds_cad_individual ci
        {BASE_WHERE}
        GROUP BY tp_cds_origem
        ORDER BY COUNT(*) DESC
    """,
    "meses": f"""
        SELECT
            COALESCE(date_trunc('month', dt_cad_individual)::date::text, 'SEM DATA') AS mes,
            COUNT(*)::text AS qtd
        FROM tb_cds_cad_individual ci
        {BASE_WHERE}
        GROUP BY 1
        ORDER BY COUNT(*) DESC
        LIMIT 24
    """,
    "anos": f"""
        SELECT
            COALESCE(EXTRACT(YEAR FROM dt_cad_individual)::int::text, 'SEM DATA') AS ano,
            COUNT(*)::text AS qtd
        FROM tb_cds_cad_individual ci
        {BASE_WHERE}
        GROUP BY 1
        ORDER BY COUNT(*) DESC
    """,
    "unidades": f"""
        SELECT
            COALESCE(us.nu_cnes, '-') AS cnes,
            COALESCE(us.no_unidade_saude, 'SEM UNIDADE') AS unidade,
            COUNT(*)::text AS qtd
        FROM tb_cds_cad_individual ci
        LEFT JOIN tb_unidade_saude us
            ON us.co_seq_unidade_saude = ci.co_unidade_saude
        {BASE_WHERE}
        GROUP BY us.nu_cnes, us.no_unidade_saude
        ORDER BY COUNT(*) DESC
        LIMIT 30
    """,
    "microareas": f"""
        SELECT
            COALESCE(NULLIF(ci.nu_micro_area, ''), 'SEM MICROAREA') AS micro_area,
            COUNT(*)::text AS qtd
        FROM tb_cds_cad_individual ci
        {BASE_WHERE}
        GROUP BY 1
        ORDER BY COUNT(*) DESC
        LIMIT 40
    """,
    "profissionais": f"""
        SELECT
            COALESCE(prof.nu_cns, '-') AS cns_profissional,
            COALESCE(prof.nu_ine, '-') AS ine,
            COALESCE(prof.nu_cbo_2002, '-') AS cbo,
            COUNT(*)::text AS qtd
        FROM tb_cds_cad_individual ci
        LEFT JOIN tb_cds_prof prof
            ON prof.co_seq_cds_prof = ci.co_cds_prof_cadastrante
        {BASE_WHERE}
        GROUP BY prof.nu_cns, prof.nu_ine, prof.nu_cbo_2002
        ORDER BY COUNT(*) DESC
        LIMIT 40
    """,
    "documentos_por_origem": f"""
        WITH base AS (
            SELECT
                ci.*,
                NULLIF(regexp_replace(COALESCE(ci.nu_cpf_cidadao, ''), '[^0-9]', '', 'g'), '') AS cpf_key,
                NULLIF(regexp_replace(COALESCE(ci.nu_cns_cidadao, ''), '[^0-9]', '', 'g'), '') AS cns_key
            FROM tb_cds_cad_individual ci
            {BASE_WHERE}
        )
        SELECT
            COALESCE(tp_cds_origem::text, '-') AS origem,
            COUNT(*)::text AS total,
            COUNT(*) FILTER (WHERE cpf_key IS NULL)::text AS sem_cpf,
            COUNT(*) FILTER (WHERE cns_key IS NULL)::text AS sem_cns,
            COUNT(*) FILTER (WHERE cpf_key IS NULL AND cns_key IS NULL)::text AS sem_cpf_e_cns
        FROM base
        GROUP BY tp_cds_origem
        ORDER BY COUNT(*) DESC
    """,
    "duplicidades": f"""
        WITH base AS (
            SELECT
                ci.*,
                NULLIF(regexp_replace(COALESCE(ci.nu_cpf_cidadao, ''), '[^0-9]', '', 'g'), '') AS cpf_key,
                NULLIF(regexp_replace(COALESCE(ci.nu_cns_cidadao, ''), '[^0-9]', '', 'g'), '') AS cns_key,
                NULLIF(upper(trim(COALESCE(ci.no_cidadao_filtro, ci.no_cidadao, ''))), '') AS nome_key,
                NULLIF(upper(trim(COALESCE(ci.no_mae_cidadao, ''))), '') AS mae_key
            FROM tb_cds_cad_individual ci
            {BASE_WHERE}
        ),
        dups AS (
            SELECT 'CPF' AS criterio, COUNT(*) AS grupos, COALESCE(SUM(qtd), 0) AS registros
            FROM (
                SELECT cpf_key, COUNT(*) qtd
                FROM base
                WHERE cpf_key IS NOT NULL
                GROUP BY cpf_key
                HAVING COUNT(*) > 1
            ) x
            UNION ALL
            SELECT 'CNS', COUNT(*), COALESCE(SUM(qtd), 0)
            FROM (
                SELECT cns_key, COUNT(*) qtd
                FROM base
                WHERE cns_key IS NOT NULL
                GROUP BY cns_key
                HAVING COUNT(*) > 1
            ) x
            UNION ALL
            SELECT 'Nome + nascimento + mae', COUNT(*), COALESCE(SUM(qtd), 0)
            FROM (
                SELECT nome_key, dt_nascimento, mae_key, COUNT(*) qtd
                FROM base
                WHERE nome_key IS NOT NULL
                    AND dt_nascimento IS NOT NULL
                GROUP BY nome_key, dt_nascimento, mae_key
                HAVING COUNT(*) > 1
            ) x
        )
        SELECT criterio, grupos::text, registros::text
        FROM dups
        ORDER BY criterio
    """,
}


SECTIONS = [
    ("totais", "Totais principais"),
    ("flags", "Sinais de possivel inflacao cadastral"),
    ("duplicidades", "Duplicidades detectaveis por chaves simples"),
    ("origem", "Distribuicao por tp_cds_origem"),
    ("documentos_por_origem", "Documentos ausentes por origem"),
    ("meses", "Meses com mais cadastros atuais ativos"),
    ("anos", "Anos com mais cadastros atuais ativos"),
    ("unidades", "Unidades com mais cadastros atuais ativos"),
    ("microareas", "Microareas com mais cadastros atuais ativos"),
    ("profissionais", "Profissionais CDS com mais cadastros atuais ativos"),
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Gera relatorio gerencial de auditoria de cadastros individuais."
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
            54,
        )
        for field in fields
    }

    def clip(value, width):
        value = str(value or "")
        return value if len(value) <= width else value[: width - 1] + "…"

    lines = []
    lines.append(" | ".join(field.ljust(widths[field]) for field in fields))
    lines.append("-+-".join("-" * widths[field] for field in fields))
    for row in rows:
        lines.append(
            " | ".join(clip(row.get(field), widths[field]).ljust(widths[field]) for field in fields)
        )
    return "\n".join(lines) + "\n"


def find_value(rows, indicator):
    for row in rows:
        if row.get("indicador") == indicator:
            try:
                return int(row.get("valor") or 0)
            except ValueError:
                return 0
    return 0


def write_report(args, data):
    totals = data["totais"]
    active_total = find_value(totals, "Versoes atuais + ativas + sem recusa")
    over_target = find_value(totals, "Diferenca ate meta de 25.000")

    with open(args.output, "w", encoding="utf-8") as report:
        report.write("RELATORIO GERENCIAL - AUDITORIA DE CADASTROS INDIVIDUAIS\n")
        report.write("=" * 72 + "\n")
        report.write(f"Gerado em          : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        report.write(f"Banco              : {args.database}@{args.host}:{args.port}\n")
        report.write("Tabela base        : tb_cds_cad_individual\n")
        report.write("Universo principal : versao atual + ativa + sem recusa\n")
        report.write("\n")

        report.write("LEITURA RAPIDA\n")
        report.write("-" * 72 + "\n")
        active_total_fmt = f"{active_total:,}".replace(",", ".")
        over_target_fmt = f"{over_target:,}".replace(",", ".")
        report.write(
            f"O sistema esta exibindo aproximadamente {active_total_fmt} cadastros no universo principal.\n"
        )
        report.write(
            f"Comparado a uma referencia de 25.000 pessoas, ha {over_target_fmt} cadastros acima do esperado.\n"
        )
        report.write(
            "Os blocos abaixo mostram onde investigar o aumento: origem, meses de pico,\n"
        )
        report.write(
            "documentos ausentes, fora de area, unidades, microareas e profissionais cadastrantes.\n\n"
        )

        for key, title in SECTIONS:
            report.write(title.upper() + "\n")
            report.write("-" * 72 + "\n")
            report.write(render_table(data[key]))
            report.write("\n")


def main():
    args = parse_args()
    data = {key: run_psql(args, QUERIES[key]) for key, _ in SECTIONS}
    write_report(args, data)

    totals = data["totais"]
    print(f"Relatorio gerado: {args.output}")
    print(f"Cadastros atuais/ativos/sem recusa: {find_value(totals, 'Versoes atuais + ativas + sem recusa')}")
    print(f"Acima de 25.000: {find_value(totals, 'Diferenca ate meta de 25.000')}")


if __name__ == "__main__":
    main()
