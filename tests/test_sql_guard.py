import pytest

from src.data.sql_guard import UnsafeQueryError, validate_read_only_sql


def test_allows_select_from_authorized_table():
    sql = "SELECT SUM(inv_neta) FROM `p.d.tb_data_bicompetitive`"
    assert validate_read_only_sql(sql, {"p.d.tb_data_bicompetitive"}).startswith("SELECT")


@pytest.mark.parametrize("verb", ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "MERGE", "TRUNCATE"])
def test_blocks_write_operations(verb):
    with pytest.raises(UnsafeQueryError):
        validate_read_only_sql(f"{verb} table_name")


def test_blocks_unknown_table():
    with pytest.raises(UnsafeQueryError):
        validate_read_only_sql("SELECT * FROM `other.dataset.table`", {"p.d.tb_data_bicompetitive"})
