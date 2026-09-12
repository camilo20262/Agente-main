"""Independent, opt-in SQL checks for the new conversation capabilities."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone


def run(output):
    from agent import build_agent_service
    from src.data.bigquery_repository import QuerySpec
    repo = build_agent_service().registry.repository
    table = repo.bicomp_table
    queries = {
        'growth_july': (f'''SELECT UPPER(TRIM(marca)) AS entity,
            SUM(IF(DATE(fecha) BETWEEN @a0 AND @a1, inv_neta, 0)) AS current_value,
            SUM(IF(DATE(fecha) BETWEEN @b0 AND @b1, inv_neta, 0)) AS previous_value,
            SUM(IF(DATE(fecha) BETWEEN @a0 AND @a1, inv_neta, -inv_neta)) AS difference
            FROM `{table}` WHERE DATE(fecha) BETWEEN @b0 AND @a1
            GROUP BY entity ORDER BY difference DESC LIMIT 1''',
            [('a0','DATE','2026-07-01'),('a1','DATE','2026-07-31'),('b0','DATE','2026-06-01'),('b1','DATE','2026-06-30')]),
        'peak_bmw': (f'''SELECT DATE_TRUNC(DATE(fecha), MONTH) AS month, SUM(inv_neta) AS value
            FROM `{table}` WHERE UPPER(TRIM(marca)) = @entity AND DATE(fecha) BETWEEN @a0 AND @a1
            GROUP BY month ORDER BY value DESC LIMIT 1''',
            [('entity','STRING','BMW'),('a0','DATE','2025-01-01'),('a1','DATE','2025-12-31')]),
        'joint_tv': (f'''SELECT SUM(IF(UPPER(TRIM(marca)) IN (@one,@two),inv_neta,0)) AS combined,
            SUM(inv_neta) AS universe,
            SAFE_DIVIDE(SUM(IF(UPPER(TRIM(marca)) IN (@one,@two),inv_neta,0)),SUM(inv_neta))*100 AS share_pct
            FROM `{table}` WHERE UPPER(TRIM(medio_agrupado)) IN (@open,@cable) AND DATE(fecha) BETWEEN @a0 AND @a1''',
            [('one','STRING','BMW'),('two','STRING','VOLVO'),('open','STRING','TV ABIERTA'),('cable','STRING','TV CABLE'),
             ('a0','DATE','2026-01-01'),('a1','DATE','2026-12-31')]),
        'joint_october': (f'''SELECT SUM(IF(UPPER(TRIM(marca)) IN (@one,@two),inv_neta,0)) AS combined,
            SUM(inv_neta) AS universe,
            SAFE_DIVIDE(SUM(IF(UPPER(TRIM(marca)) IN (@one,@two),inv_neta,0)),SUM(inv_neta))*100 AS share_pct
            FROM `{table}` WHERE DATE(fecha) BETWEEN @a0 AND @a1''',
            [('one','STRING','BMW'),('two','STRING','VOLVO'),('a0','DATE','2025-10-01'),('a1','DATE','2025-10-31')]),
        'empty_week_toyota': (f'''SELECT COUNT(*) AS source_rows, SUM(inv_neta) AS value FROM `{table}`
            WHERE UPPER(TRIM(marca))=@entity AND DATE(fecha) BETWEEN @a0 AND @a1''',
            [('entity','STRING','TOYOTA'),('a0','DATE','2024-03-25'),('a1','DATE','2024-03-31')]),
        'bmw_october': (f'''SELECT SUM(inv_neta) AS value FROM `{table}`
            WHERE UPPER(TRIM(marca))=@entity AND DATE(fecha) BETWEEN @a0 AND @a1''',
            [('entity','STRING','BMW'),('a0','DATE','2025-10-01'),('a1','DATE','2025-10-31')]),
    }
    results = {'executed_at': datetime.now(timezone.utc).isoformat(), 'checks': {}}
    for name, (sql, parameters) in queries.items():
        result = repo._execute(QuerySpec(sql, parameters))
        results['checks'][name] = result
        print(name, result['rows'], flush=True)
    Path(output).write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str)+'\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--output',required=True);a=p.parse_args()
    if not a.live:p.error('Requires --live.')
    run(a.output)
