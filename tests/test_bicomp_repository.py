from types import SimpleNamespace

from src.config import Settings
from src.data.bigquery_repository import BigQueryRepository


class FakeRow(dict):
    def items(self):
        return super().items()


class FakeJob:
    total_bytes_processed = 128
    def __init__(self, rows=None): self._rows = rows or []
    def result(self): return self._rows


class FakeClient:
    def __init__(self): self.queries = []
    def get_table(self, table):
        fields = {
            "fecha": "DATE", "marca": "STRING", "anunciante": "STRING", "medio": "STRING",
            "pais": "STRING", "inv_neta": "NUMERIC", "total_insercion": "INTEGER",
        }
        return SimpleNamespace(schema=[SimpleNamespace(name=name, field_type=typ) for name, typ in fields.items()])
    def query(self, sql, job_config, location):
        self.queries.append((sql, job_config, location))
        if job_config.dry_run:
            return FakeJob()
        if "SUM(`inv_neta`)" in sql:
            if "GROUP BY dimension" in sql:
                return FakeJob([FakeRow(dimension="Renault", value=900, source_rows=4), FakeRow(dimension="Volvo", value=350, source_rows=2)])
            return FakeJob([FakeRow(value=1250, source_rows=8)])
        return FakeJob([FakeRow(marca="Volvo")])


def settings():
    return Settings(gcp_project_id="nexuslatam-master", bigquery_dataset="NEXUS_GROUPM_BI_2", bigquery_bicomp_table="tb_data_bicompetitive")


def test_connection_uses_expected_table_and_limit():
    client = FakeClient()
    rows = BigQueryRepository(settings(), client=client).test_connection()
    assert rows == [{"marca": "Volvo"}]
    assert "`nexuslatam-master.NEXUS_GROUPM_BI_2.tb_data_bicompetitive`" in client.queries[0][0]
    assert "LIMIT 5" in client.queries[0][0]


def test_investment_filters_are_query_parameters():
    client = FakeClient()
    result = BigQueryRepository(settings(), client=client).consultar_inversion(metric="inv_neta", filters={"marca": "Volvo"}, start_date="2026-01-01")
    sql, config, _ = client.queries[-1]
    assert "Volvo" not in sql
    assert "UPPER(CAST(`marca` AS STRING))" in sql
    assert "@filter_0" in sql and "@start_date" in sql
    assert {p.name for p in config.query_parameters} == {"filter_0", "start_date"}
    assert result["value"] == 1250
    assert result["row_count"] == 8
    assert result["evidence"]["bytes_processed"] == 128


def test_rejects_unknown_fields_before_query():
    repository = BigQueryRepository(settings(), client=FakeClient())
    try:
        repository.consultar_inversion(filters={"campo_inventado": "x"})
    except ValueError as exc:
        assert "no permitido" in str(exc)
    else:
        raise AssertionError("Expected invalid field to be rejected")


def test_rejects_metric_outside_allowlist():
    repository = BigQueryRepository(settings(), client=FakeClient())
    try:
        repository.consultar_inversion(metric="precio_inventado")
    except ValueError as exc:
        assert "no permitido" in str(exc)
    else:
        raise AssertionError("Expected invalid metric to be rejected")


def test_array_filters_use_array_query_parameter():
    client = FakeClient()
    BigQueryRepository(settings(), client=client).consultar_inversion(filters={"marca": ["Volvo", "Renault"]})
    sql, config, _ = client.queries[-1]
    assert "IN UNNEST(@filter_0)" in sql
    parameter = config.query_parameters[0]
    assert parameter.name == "filter_0"
    assert parameter.values == ["VOLVO", "RENAULT"]


def test_compare_brands_is_deterministic():
    result = BigQueryRepository(settings(), client=FakeClient()).comparar_marcas(brand_a="Volvo", brand_b="Renault")
    assert result["difference"] == 0
    assert result["difference_pct"] == 0
    assert result["ratio_a_over_b"] == 1


def test_brand_ranking_is_ordered_by_bigquery():
    result = BigQueryRepository(settings(), client=FakeClient()).ranking_marcas(filters=None, start_date=None, end_date=None, limit=5)
    assert result["dimension"] == "marca"
    assert result["rows"][0]["dimension"] == "Renault"
    assert result["row_count"] == 2


def test_generic_and_specialized_brand_rankings_are_equivalent(monkeypatch):
    repo = BigQueryRepository(settings(), client=FakeClient())
    specs = []
    rows = [{"dimension": "Volvo", "value": 350, "source_rows": 2}]

    def execute(spec):
        specs.append(spec)
        return {"rows": rows, "evidence": {"bytes_processed": 128, "duration_ms": 1}}

    monkeypatch.setattr(repo, "_execute_bicomp", execute)
    arguments = {"metric": "inv_neta", "filters": {"marca": ["Volvo", "Renault"], "medio": "DIGITAL"},
                 "start_date": "2026-01-01", "end_date": "2026-01-31", "limit": 5}
    specialized = repo.ranking_marcas(**arguments)
    generic = repo.ranking(dimension="marca", **arguments)
    assert len(specs) == 2
    assert specs[0] == specs[1]  # Identical SQL and parameter names/types/values.
    assert "`marca` AS dimension" in specs[0].sql
    assert "GROUP BY dimension ORDER BY value DESC LIMIT @limit" in specs[0].sql
    assert ("limit", "INT64", 5) in specs[0].parameters
    assert generic == specialized
    assert generic["dimension"] == "marca"
    assert generic["filters"] == arguments["filters"]
    assert generic["rows"] == rows
